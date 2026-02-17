# SigPro Skill Specialization Roles

This is the role split for SigPro, similar to DailyVerse but optimized for voice-command operations.

## 1) Ingress Role — Signal Intake

**Purpose:** Receive and normalize inbound Signal voice messages.

**Owns:**
- Source metadata capture (sender, timestamp, thread/context)
- Input validation (voice note present, file readable)
- Routing into pipeline

## 2) Transcription Role — Speech to Text

**Purpose:** Convert audio into high-quality transcript.

**Owns:**
- Audio preprocessing checks
- STT call execution
- Confidence signals and fallback markers

## 3) Prompt Compiler Role — Intent Structuring

**Purpose:** Transform transcript into a structured OpenClaw command prompt.

**Owns:**
- Command extraction
- Parameter normalization
- Clarification prompts when intent is incomplete

## 4) Guardrail Role — Safety + Policy

**Purpose:** Decide whether to execute, ask for confirmation, or reject.

**Owns:**
- Ambiguity detection
- Risk classification
- Allowed-action policy checks

## 5) Executor Role — OpenClaw Action Runner

**Purpose:** Execute approved prompts and collect outcomes.

**Owns:**
- Tool/action invocation
- Retry behavior for transient errors
- Structured result packaging

## 6) Ops Role — Observability + Reliability

**Purpose:** Track pipeline health and quality.

**Owns:**
- Stage-level logs
- Failure categorization
- Latency + success metrics

## Operating Rule

If transcript confidence is low or intent is ambiguous, SigPro should ask for confirmation before execution.
