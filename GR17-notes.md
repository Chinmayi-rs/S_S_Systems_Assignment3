# GR-17 HTTPS Integration

## Implementation
- nginx provides browser-facing HTTPS for the voting application.
- Only TLS 1.3 is enabled.
- HTTP on localhost port 8080 redirects to HTTPS on port 8443.
- nginx forwards requests to the web service on port 8080.
- The web container has no published host port.
- Certificates are mounted read-only into nginx.
- Generated certificates and private keys are excluded from Git
  and the application Docker build.
- The Flask debugger is disabled.

## Setup
Run these commands from the project folder in PowerShell.

Create a virtual environment:
python -m venv .venv

Install dependencies:
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Generate the local certificate once:
.\.venv\Scripts\python.exe scripts/generate_certificate.py

Start Docker Desktop, then run:
docker compose up --build -d

Check container status:
docker compose ps

Open:
https://localhost:8443

The certificate is self-signed, so a browser trust warning is
expected for this local demonstration.

## Verification
Record the actual results:
- Application tests:
- HTTPS health response:
- Login and enrolment through HTTPS:
- HTTP 308 redirect:
- TLS 1.3 negotiation:
- TLS 1.2 rejection: passed with TLSV1_ALERT_PROTOCOL_VERSION

## Stop
docker compose down

Stopping the web container loses its temporary tmpfs database.
Do not use it to retain election records.

## Certificate handling
The generated certificate is valid for 30 days.
Keep localhost.key private and do not upload nginx/certs.
Generate a replacement certificate when the existing one expires.

## Limitations
- The localhost certificate is self-signed.
- nginx-to-Flask traffic uses HTTP inside Docker.
- The Flask development server remains in use.
- Existing development secrets are unsuitable for production.
- Database storage uses tmpfs and is temporary.
- The configuration is for local demonstration.
- Integration with other team branches requires review,
  including preserving GR-18 and GR-19 changes.