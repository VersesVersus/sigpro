# SigPro Authentication Policy

## Two-Channel Out-of-Band Auth (OOB)

To execute a command transcribed from Signal voice, a matching 4-digit code must be provided.

1. **Code Generation**: A random 4-digit numeric code is generated.
2. **Delivery (Out-of-Band)**: The code is sent to the user via **WhatsApp**.
3. **Submission (In-Band)**: The user provides the code via **Signal text**.
4. **Validation**: The command only proceeds to execution if the Signal-submitted code matches the active WhatsApp-delivered code.
5. **Expiration**: Codes expire after 5 minutes or after one successful use.
