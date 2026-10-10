# Security Policy

## Reporting a Vulnerability

The VaultProxy project takes security seriously. If you discover a security vulnerability or potential privacy leak, please report it to us privately via GitHub's private vulnerability reporting feature.

### How to Report
- Please navigate to the **Security** tab of the GitHub repository and submit a **Private Vulnerability Report**.
- Do NOT open a public issue or discussion for security vulnerabilities.
- **Include**:
  - Detailed description of the issue.
  - Steps to reproduce or proof-of-concept payload.
  - Expected vs actual behavior.
  - Impact assessment.

### Response SLA
- **Acknowledgment**: Within 24 hours.
- **Triage & Remediation Plan**: Within 72 hours.
- **Fix Release**: As soon as possible depending on severity (critical issues prioritized immediately).

## Scope
- Masking engine bypasses or leaks of raw PII/secrets to upstream servers.
- Authentication bypass or unauthorized access in production profile.
- Log leakage of unmasked sensitive content.
- Unhandled crashes causing fail-open behavior in STRICT_MODE.
