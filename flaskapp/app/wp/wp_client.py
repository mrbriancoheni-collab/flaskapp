# app/wp/wp_client.py
from __future__ import annotations

import base64
import json
import mimetypes
import os
import datetime as dt
from typing import Iterable, Optional, Union, Tuple, Dict
from urllib.parse import urljoin, urlencode

import requests
from requests.adapters import HTTPAdapter, Retry


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)


class WPClient:
    """
    Minimal WordPress REST client using Application Passwords (Basic Auth).

    - Retries with backoff
    - Neutral browser UA to avoid 'bot' blocks
    - Auto-fallback to index.php?rest_route=… when /wp-json/ is blocked (403/404)
    - Safer JSON posting
    - Media upload with proper headers
    - Helpers for terms, posts (create/update), and scheduling
    - auth_check(): diagnostic helper that tolerates edge protection
    """

    def __init__(self, base: str, user: str, app_pw: str, timeout: float = 15.0):
        self.base = (base or "").rstrip("/")
        token = base64.b64encode(f"{user}:{app_pw}".encode("utf-8")).decode("utf-8")
        self._auth = {"Authorization": f"Basic {token}"}
        self._timeout = timeout

        self._s = requests.Session()
        self._s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        retries = Retry(
            total=3,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST", "PUT", "PATCH", "DELETE"]),
            raise_on_status=False,
        )
        self._s.mount("https://", HTTPAdapter(max_retries=retries))
        self._s.mount("http://", HTTPAdapter(max_retries=retries))

    # ---------- internals ----------

    def _canon_url(self, path: str) -> str:
        """Canonical REST URL builder. Accepts '/wp-json/...' or '/wp/v2/...'. """
        if not path.startswith("/"):
            path = "/" + path
        # If caller already passed '/wp-json/...', great. If they passed '/wp/v2/...', prepend '/wp-json'.
        if path.startswith("/wp-json/"):
            return urljoin(self.base + "/", path.lstrip("/"))
        else:
            return urljoin(self.base + "/", f"wp-json{path}")

    def _alt_url(self, path: str) -> str:
        """Alternate REST route via index.php?rest_route=... (helps on some shared hosts/WAFs)."""
        if not path.startswith("/"):
            path = "/" + path
        # Strip optional /wp-json prefix when building rest_route
        rest_path = path[8:] if path.startswith("/wp-json") else path
        return urljoin(self.base + "/", "index.php") + "?" + urlencode({"rest_route": rest_path})

    def _build_urls(self, path: str) -> Tuple[str, str]:
        """Return (canonical_url, alt_url)."""
        return self._canon_url(path), self._alt_url(path)

    def _req(
        self,
        method: str,
        path: str,
        *,
        json_body=None,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        data=None,
        files=None,
    ):
        hdrs = dict(self._auth)
        if headers:
            hdrs.update(headers)
        if json_body is not None and "Content-Type" not in hdrs and files is None and data is None:
            hdrs["Content-Type"] = "application/json"

        url1, url2 = self._build_urls(path)
        last_exc = None

        # Try canonical first
        for idx, url in enumerate((url1, url2)):
            try:
                resp = self._s.request(
                    method,
                    url,
                    params=params,
                    data=(json.dumps(json_body) if json_body is not None and files is None and data is None else data),
                    files=files,
                    headers=hdrs,
                    timeout=self._timeout,
                )
                # If canonical returns 403/404, try the alt route automatically once.
                if idx == 0 and resp.status_code in (403, 404):
                    continue
                resp.raise_for_status()
                return resp
            except requests.HTTPError as he:
                last_exc = he
                # If first attempt failed with 403/404, the loop will try alt URL next.
            except Exception as e:
                last_exc = e

        # Build a more helpful error on final failure
        if isinstance(last_exc, requests.HTTPError) and last_exc.response is not None:
            s = last_exc.response.status_code
            body = ""
            try:
                body = (last_exc.response.text or "")[:500]
            except Exception:
                pass
            if s == 403:
                hint = (
                    "403 from WordPress REST API. Likely blocked by Cloudflare/WAF or a security plugin. "
                    "Allow /wp-json/wp/v2/* and/or index.php?rest_route=/wp/v2/* and ensure Authorization "
                    "header is passed through. Body (truncated): "
                )
                raise requests.HTTPError(f"{hint}{body}") from last_exc
            raise requests.HTTPError(f"WP API error {s}. Body (truncated): {body}") from last_exc
        raise last_exc

    # ---------- diagnostics ----------

    def auth_check(self) -> dict:
        """
        Probe endpoints that commonly work even when /users/me is blocked by WAF.
        Returns {ok, status?, error?, body?, author?}
        """
        # 1) API index (some sites block this; ok to report failure)
        try:
            _ = self._req("GET", "/wp-json/").json()
        except Exception as e:
            return {"ok": False, "error": f"WP index unreachable: {e}"}

        # 2) Safer capability probe: /types (often allowed)
        try:
            _ = self._req("GET", "/wp/v2/types").json()
        except Exception as e:
            # Still fine; continue to try users/me for author id
            pass

        # 3) Try users/me (may 403 behind Cloudflare)
        try:
            me = self._req("GET", "/wp/v2/users/me").json()
            return {"ok": True, "author": me.get("id")}
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            body = ""
            try:
                body = e.response.text[:2000]
            except Exception:
                pass
            return {"ok": False, "status": status, "error": str(e), "body": body}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------- user & terms ----------

    def me(self) -> dict:
        r = self._req("GET", "/wp/v2/users/me")
        return r.json()

    def ensure_term(self, name: str, taxonomy: str = "categories") -> int:
        if not name:
            raise ValueError("term name required")
        base_path = "/wp/v2/categories" if taxonomy == "categories" else "/wp/v2/tags"

        r = self._req("GET", base_path, params={"search": name, "per_page": 100})
        for t in r.json():
            if (t.get("name") or "").strip().lower() == name.strip().lower():
                return int(t["id"])

        r = self._req("POST", base_path, json_body={"name": name})
        return int(r.json()["id"])

    def ensure_terms(self, names: Iterable[str], taxonomy: str) -> list[int]:
        ids: list[int] = []
        for n in (names or []):
            n = (n or "").strip()
            if not n:
                continue
            ids.append(self.ensure_term(n, taxonomy=taxonomy))
        return ids

    # ---------- media ----------

    def upload_image(self, path: str, alt_text: str = "") -> int:
        if not os.path.exists(path):
            raise FileNotFoundError(path)

        url = "/wp/v2/media"
        filename = os.path.basename(path)
        ctype, _ = mimetypes.guess_type(filename)
        ctype = ctype or "application/octet-stream"

        with open(path, "rb") as fh:
            files = {"file": (filename, fh, ctype)}
            r = self._req("POST", url, files=files)

        media = r.json()
        if alt_text:
            self._req("POST", f"/wp/v2/media/{media['id']}", json_body={"alt_text": alt_text})
        return int(media["id"])

    # ---------- posts ----------

    def create_or_update_post(
        self,
        *,
        post_id: Optional[int] = None,
        title: str,
        html: str,
        excerpt: Optional[str] = None,
        status: str = "draft",
        publish_dt: Optional[dt.datetime] = None,
        categories: Optional[Union[list[int], list[str]]] = None,
        tags: Optional[Union[list[int], list[str]]] = None,
        yoast_title: Optional[str] = None,
        yoast_desc: Optional[str] = None,
        faq_jsonld: Optional[str] = None,
        featured_media: Optional[int] = None,
    ) -> dict:

        cat_ids: Optional[list[int]] = None
        tag_ids: Optional[list[int]] = None
        if categories:
            if all(isinstance(c, int) for c in categories):
                cat_ids = list(categories)
            else:
                cat_ids = self.ensure_terms([str(c) for c in categories], taxonomy="categories")
        if tags:
            if all(isinstance(t, int) for t in tags):
                tag_ids = list(tags)
            else:
                tag_ids = self.ensure_terms([str(t) for t in tags], taxonomy="tags")

        payload: dict = {"title": title, "content": html, "status": status}
        if excerpt:
            payload["excerpt"] = excerpt
        if cat_ids:
            payload["categories"] = cat_ids
        if tag_ids:
            payload["tags"] = tag_ids
        if featured_media:
            payload["featured_media"] = featured_media

        if publish_dt and status == "future":
            # WordPress expects GMT for future-dated posts
            if publish_dt.tzinfo is None:
                payload["date_gmt"] = publish_dt.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                payload["date_gmt"] = publish_dt.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        # Yoast & custom meta
        meta = {}
        if yoast_title:
            meta["_yoast_wpseo_title"] = yoast_title
        if yoast_desc:
            meta["_yoast_wpseo_metadesc"] = yoast_desc
        if faq_jsonld:
            meta["_fs_faq_jsonld"] = faq_jsonld
        if meta:
            payload["meta"] = meta

        if post_id:
            r = self._req("POST", f"/wp/v2/posts/{post_id}", json_body=payload)  # WP accepts POST for update
        else:
            r = self._req("POST", "/wp/v2/posts", json_body=payload)
        return r.json()

    def get_post(self, post_id: int) -> dict:
        r = self._req("GET", f"/wp/v2/posts/{int(post_id)}")
        return r.json()

    # ---------- diagnostics bundle ----------

    def site_health(self) -> dict:
        info = {}
        try:
            info["index"] = self._req("GET", "/wp-json/").json()
        except Exception as e:
            info["index_error"] = str(e)
        try:
            info["types"] = self._req("GET", "/wp/v2/types").json()
        except Exception as e:
            info["types_error"] = str(e)
        try:
            info["me"] = self.me()
        except Exception as e:
            info["me_error"] = str(e)
        return info
