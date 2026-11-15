CREATE TABLE IF NOT EXISTS captured_leads (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  email          VARCHAR(254) NOT NULL,
  tool_name      VARCHAR(100),
  detected_trade VARCHAR(100),
  service_area   VARCHAR(200),
  result_summary TEXT,
  source         VARCHAR(100) DEFAULT 'free_tool',
  ip_hash        VARCHAR(64),
  created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_email   (email),
  INDEX idx_tool    (tool_name),
  INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
