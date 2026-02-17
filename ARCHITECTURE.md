# SigPro Architecture

## Pipeline

1. **Signal Ingress (via OpenClaw + shared dispatcher)**
   - OpenClaw receives inbound Signal messages
   - Main/session router publishes events to shared dispatcher bus
   - SigPro consumes new events by consumer cursor (no direct `signal-cli receive`)
2. **Audio Transcription**
   - Use ElevenLabs to convert audio -> text
3. **Prompt Normalization**
   - Convert transcript into structured command prompt
4. **Guardrails**
   - Confidence checks
   - Intent/scope validation
   - Safety policy checks
5. **Execution**
   - Run approved command in OpenClaw toolchain
6. **Response**
   - Return execution result (or clarification request)

## Guardrails

- Do not auto-execute low-confidence transcripts
- Require clarification when intent is ambiguous
- Log all stage failures with actionable errors
- Keep permissions constrained to approved tools/actions

## Observability Targets

- Per-stage success/failure counters
- End-to-end latency
- Transcription confidence distribution
- Clarification-request rate
- Execution success rate
