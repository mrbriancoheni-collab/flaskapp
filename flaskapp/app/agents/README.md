# Multi-Agent AI System for Google Ads Optimization

## Overview

This is a **goal-oriented, multi-agent AI system** that autonomously manages Google Ads campaigns. Unlike traditional rule-based automation tools, our agents **plan, execute, learn, and adapt** to achieve business goals.

## Architecture

The system is organized into **three layers**, each with specialized agents:

```
┌─────────────────────────────────────────────────────┐
│          STRATEGIC LAYER (Director Agent)           │
│  • Sets quarterly goals & KPIs                      │
│  • Allocates budget across campaigns                │
│  • Decides when to launch/pause/scale               │
│  • Long-term planning (90-day outlook)              │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│         OPERATIONAL LAYER (Manager Agents)          │
│  Campaign Manager  │  Budget Manager  │  QA Manager │
│  • Daily spend     │ • Pacing         │ • QS trends │
│  • Performance     │ • Reallocation   │ • Ad testing│
│  • Bid strategy    │ • ROI tracking   │ • CTR opt.  │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│          TACTICAL LAYER (Executor Agents)           │
│  Keyword Agent  │ Ad Copy Agent │ Negative KW Agent │
│  • Bid adj      │ • A/B tests   │ • Search terms   │
│  • Match types  │ • Headlines   │ • Exclusions     │
│  • Additions    │ • Descriptions│ • Broad match    │
└─────────────────────────────────────────────────────┘
```

## Agent Catalog

### Strategic Layer

#### **Strategic Director Agent** 🎯
**Tagline:** *"Your CMO for Google Ads"*

**What it does:**
- Sets quarterly business goals (e.g., "Reduce CPL from $80 to $60 in 90 days")
- Allocates budget across campaigns based on ROAS
- Identifies scaling opportunities (high ROAS + low impression share)
- Pauses consistently underperforming campaigns
- Considers seasonality and business context

**Operates:** Weekly/Monthly cycles

**Example Decisions:**
- "Reallocate $2,000/month from Campaign A (0.5x ROAS) to Campaign B (3.2x ROAS)"
- "Scale HVAC Installation campaign by 50% - it's peak season and campaign has 4.5x ROAS"
- "Pause Commercial Services campaign - consistent 0.3x ROAS after 90 days"

---

### Operational Layer

#### **Campaign Manager Agent** 📊
**Tagline:** *"24/7 performance monitoring"*

**What it does:**
- Monitors all campaigns every hour
- Detects performance anomalies (CPL spikes, conversion drops)
- Makes bid adjustments to maintain target CPL
- Delegates tactical work to specialist agents
- Escalates strategic issues to Director

**Operates:** Hourly/Daily cycles

**Example Decisions:**
- "CPL spiked 45% in Campaign X - reduce bids by 15% and investigate cause"
- "Delegate to Quality Score Agent: Diagnose why Campaign Y's QS dropped from 7 to 4"
- "Conversion rate dropped 35% - escalate to Strategic Director for review"

#### **Budget Guardian Agent** 💰
**Tagline:** *"Stops wasted spend before it happens"*

**What it does:**
- Monitors budget pacing (on track to overspend?)
- Detects runaway campaigns (3x normal daily spend)
- Adjusts daily budgets to prevent overruns
- Emergency pauses for unusual spend patterns

**Operates:** Hourly cycles

**Example Decisions:**
- "Campaign spent $850 yesterday vs $120 average - EMERGENCY PAUSE for investigation"
- "On track to overspend by $1,200 - reduce daily budget from $200 to $135"
- "Budget 80% spent with 15 days remaining - slow pacing to prevent early depletion"

#### **Quality Score Doctor Agent** ⭐
**Tagline:** *"Lower your CPCs automatically"*

**What it does:**
- Monitors Quality Scores for all keywords
- Diagnoses root causes (ad relevance, landing page, CTR)
- Delegates fixes to appropriate agents
- Tracks QS improvements and CPC reductions

**Operates:** Daily cycles

**Example Decisions:**
- "Keyword 'emergency plumber' has QS 3/10 - delegate ad rewrite to Ad Copy Agent"
- "20 keywords have 'Below Average' landing page experience - escalate to Director"
- "QS improvements saved $420 in CPC this month - continue monitoring"

---

### Tactical Layer

#### **Keyword Optimizer Agent** 🔑
**Tagline:** *"Bid management on autopilot"*

**What it does:**
- Optimizes bids at keyword level
- Pauses keywords with no conversions after $200 spend
- Increases bids for high-performers below target CPA
- Adds proven search terms as new keywords

**Operates:** Daily cycles

**Example Decisions:**
- "Pause keyword 'hvac repair' - spent $280 with 0 conversions"
- "Increase bid 25% for 'furnace installation' - CPA $45 vs $80 target"
- "Add 'emergency furnace repair chicago' as new keyword - proven 3 conversions at $42 CPA"

#### **Negative Keyword Agent** 🚫
**Tagline:** *"Your search term detective"*

**What it does:**
- Reviews search term reports daily
- Identifies irrelevant/wasteful searches
- Adds negative keywords automatically
- Builds negative keyword lists by theme

**Operates:** Daily cycles

**Example Decisions:**
- "Block 'free plumber estimate' - spent $85 with 0 conversions (contains 'free')"
- "Block 'plumber salary' - irrelevant job seeker query"
- "Block 'diy furnace repair' - not a commercial intent search"

**Auto-execution:** 95% confident - blocking waste is very safe

#### **Ad Copy Scientist Agent** ✍️
**Tagline:** *"A/B tests while you sleep"*

**What it does:**
- Creates new ad variations for testing
- Runs A/B tests to identify winners
- Pauses underperforming ads (30% below average CTR)
- Improves ad relevance for Quality Score

**Operates:** Weekly cycles

**Example Decisions:**
- "Create 2 new ad variations for 'HVAC Installation' ad group - only 1 ad currently"
- "Pause Ad #12 - CTR 1.8% vs 3.2% group average after 1,000 impressions"
- "Rewrite ads for 'furnace repair' keyword to improve QS from 4 to 7"

---

## Key Features

### 1. **Autonomous Execution**

Agents automatically execute **low-risk decisions** without approval:

```python
def should_auto_execute(self, decision: AgentDecision) -> bool:
    return (
        decision.risk_level == DecisionRiskLevel.LOW and
        decision.confidence >= self.auto_execute_threshold and
        AgentCapability.AUTONOMOUS_EXECUTION in self.capabilities
    )
```

**Examples of auto-executed decisions:**
- Add negative keyword "free" (99% confidence)
- Pause keyword with $200 spend + 0 conversions (95% confidence)
- Reduce bids by 10% when CPL exceeds target (92% confidence)

**Examples requiring approval:**
- Budget changes (high risk)
- Pause entire campaigns (high risk)
- New campaign launches (medium risk, strategic decision)

### 2. **Multi-Agent Coordination**

Agents communicate via **Event Bus** for coordinated workflows:

```python
# Campaign Manager detects CPL spike
event_bus.emit('campaign_performance_alert', {
    'campaign_id': '12345',
    'cpl_spike': 45
})

# Quality Score Agent subscribes to alerts
def handle_performance_alert(event):
    # Investigate Quality Score issues
    findings = diagnose_quality_score(event.data['campaign_id'])

    # Report back
    event_bus.emit('delegation_complete', {
        'findings': findings,
        'recommendations': [...]
    })
```

**Example workflow:**
1. Strategic Director notices declining ROAS → Emits `campaign_performance_alert`
2. Campaign Manager investigates → Delegates to Quality Score Agent
3. Quality Score Agent diagnoses → Delegates ad rewrite to Ad Copy Agent
4. Ad Copy Agent creates new ads → Reports completion
5. Campaign Manager monitors results → Reports back to Director

### 3. **Learning & Adaptation**

Agents track **predicted vs. actual outcomes** and improve over time:

```python
# Agent makes prediction
decision = AgentDecision(
    decision_type='adjust_bid',
    predicted_outcome={'cpl_reduction': 12.0}  # Predicts $12 CPL drop
)

# 30 days later: actual outcome measured
actual_outcome = {'cpl_reduction': 10.5}  # Actually dropped $10.50

# Agent learns from accuracy
agent.learn(decision, actual_outcome)
# → Accuracy: 87.5%
# → Updates confidence model for future bid adjustments
```

**Adaptive behavior:**
- If predictions are consistently wrong (<70% accuracy), agent becomes more conservative
- If predictions are consistently right (>85% accuracy), agent becomes more aggressive
- Confidence thresholds adjust based on historical performance

### 4. **Goal-Oriented Planning**

Strategic Director works **backwards from goals** to create multi-step plans:

```python
# Business goal: Reduce CPL from $80 to $60 in 90 days
plan = strategic_director.create_plan(goal={
    'metric': 'cpl',
    'current': 80,
    'target': 60,
    'timeframe_days': 90
})

# Generated plan:
Week 1: Audit & pause worst-performing keywords (-$8 CPL)
Week 2: Improve QS on top 20 keywords (-$6 CPL via lower CPC)
Week 3: Test 5 new ad variations (-$3 CPL via improved CTR)
Week 4: Add 50 long-tail keywords (-$3 CPL via cheaper clicks)
# ... continues with weekly milestones
```

Each week, sub-agents execute their part and report back. Plan adjusts based on results.

### 5. **Transparency & Auditability**

All agent decisions are logged in **Decision Log** for full transparency:

```sql
SELECT * FROM agent_decisions
WHERE account_id = 123
ORDER BY created_at DESC;

-- Shows:
-- - What decision was made
-- - Why (reasoning)
-- - Expected impact
-- - Actual impact (after execution)
-- - Prediction accuracy
```

**Analytics dashboard shows:**
- Decisions by agent type
- Auto-executed vs. approval-required
- Prediction accuracy trends
- Total savings/leads generated
- Agent confidence scores

---

## Technical Implementation

### Event Bus

Publish-subscribe pattern for inter-agent communication:

```python
from app.agents import EventBus

event_bus = EventBus()

# Subscribe to events
event_bus.subscribe('cpl_spike', campaign_manager.handle_cpl_spike)

# Emit events
event_bus.emit('cpl_spike', {
    'campaign_id': '12345',
    'spike_pct': 45
})
```

### Decision Log

Tracks all decisions for learning and analytics:

```python
from app.agents import DecisionLog

decision_log = DecisionLog()

# Log decision
decision_log.log_decision(decision)

# Log execution
decision_log.log_execution(decision, result)

# Log learning
decision_log.log_learning(decision, actual_outcome, accuracy)

# Get performance metrics
stats = decision_log.get_agent_performance('campaign_manager')
```

### Running Agents

```python
from app.agents import (
    StrategicDirectorAgent,
    CampaignManagerAgent,
    NegativeKeywordAgent,
    EventBus,
    DecisionLog
)

# Initialize infrastructure
event_bus = EventBus()
decision_log = DecisionLog()

# Initialize agents
strategic_director = StrategicDirectorAgent(
    event_bus=event_bus,
    decision_log=decision_log
)

campaign_manager = CampaignManagerAgent(
    event_bus=event_bus,
    decision_log=decision_log
)

negative_keyword_agent = NegativeKeywordAgent(
    event_bus=event_bus,
    decision_log=decision_log
)

# Prepare context (from Google Ads API)
context = {
    'performance_90d': {...},
    'campaigns': [...],
    'keywords': [...],
    'search_terms': [...]
}

# Run agent cycle
result = campaign_manager.run_cycle(context, google_ads_client)

# Result:
{
    'opportunities_found': 12,
    'decisions_made': 8,
    'auto_executed': 6,  # 6 low-risk decisions executed
    'pending_approval': 2  # 2 high-risk decisions waiting for approval
}
```

---

## Competitive Differentiation

**vs. WordStream/Optmyzr/Adalysis:**

| Feature | Competitors | Our Agentic System |
|---------|-------------|-------------------|
| **Automation** | Rule-based | Goal-oriented AI |
| **Execution** | Show recommendations | Auto-execute safe changes |
| **Learning** | Static rules | Learns from outcomes |
| **Coordination** | Single-agent | Multi-agent collaboration |
| **Planning** | Reactive | Proactive goal planning |

**Our messaging:**
> "Other tools give you recommendations. **Our AI agents do the work.**
> While WordStream shows you a list of tasks, our Campaign Manager is already optimizing your bids.
> While Optmyzr sends you a report, our Budget Guardian has already reallocated $500 from a dying campaign to your best performer.
> **You don't manage the tool. The tool manages your ads.**"

---

## Roadmap

### Phase 1: Foundation (Complete)
- ✅ Base agent architecture
- ✅ Event bus for communication
- ✅ Decision log for tracking
- ✅ Strategic, operational, and tactical agents

### Phase 2: Integration (Next)
- [ ] Connect to Google Ads API for real execution
- [ ] Build approval queue UI for high-risk decisions
- [ ] Add agent performance dashboard
- [ ] Database migration for agent_decisions table

### Phase 3: Learning (Month 3-4)
- [ ] Prediction accuracy tracking
- [ ] Confidence model updates
- [ ] A/B test different agent strategies
- [ ] Benchmark against human performance

### Phase 4: Advanced Features (Month 5+)
- [ ] LLM integration for ad copy generation
- [ ] Seasonality detection from industry data
- [ ] Competitive intelligence integration
- [ ] Cross-account learning (privacy-preserving)

---

## License

Proprietary - FieldSprout AI Agents
