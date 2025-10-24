# app/forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Optional, Length

class ChatForm(FlaskForm):
    prompt = TextAreaField(
        "Prompt",
        validators=[DataRequired(), Length(max=4000)],
        render_kw={"rows": 6, "placeholder": "Ask anything…"}
    )
    submit = SubmitField("Send")

class GuidedQuestionsForm(FlaskForm):
    industry = StringField("Industry", validators=[DataRequired(), Length(max=120)])
    services = TextAreaField("Core services", validators=[DataRequired(), Length(max=1000)])
    locations = StringField("Service area (cities/ZIPs)", validators=[DataRequired(), Length(max=300)])
    ideal_customers = TextAreaField("Ideal customer profile", validators=[Optional(), Length(max=1000)])
    pain_points = TextAreaField("Top customer pain points", validators=[Optional(), Length(max=1000)])
    differentiators = TextAreaField("What makes you different?", validators=[Optional(), Length(max=1000)])
    competitors = TextAreaField("Main competitors (optional)", validators=[Optional(), Length(max=500)])
    goals = TextAreaField("Business goals (3–6 months)", validators=[Optional(), Length(max=800)])
    tone = StringField("Brand voice/tone (optional)", validators=[Optional(), Length(max=120)])
    budget = StringField("Avg. ticket / budget (optional)", validators=[Optional(), Length(max=120)])

    submit_ask = SubmitField("Ask AI for Suggestions")
    submit_save = SubmitField("Save Answers")
