# Security

## Supported versions

Security fixes are applied to the latest release.

## Reporting a vulnerability

Please report vulnerabilities through GitHub's private vulnerability reporting
for this repository. Do not include secrets or private project data in a public
issue.

## Security model

agent-ledger is a local coordination tool, not a security boundary. The SQLite
database and dashboard contain project activity and may contain text entered by
users or agents. Keep `.agent-ledger/` out of version control and protect the
project directory with normal operating-system permissions.

The dashboard has no authentication. It binds to loopback by default and
refuses a non-loopback address unless `--unsafe-expose` is supplied. Do not
expose it on an untrusted network.
