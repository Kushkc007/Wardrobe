# Security Policy

## Supported versions

The `main` branch receives security and bug fixes.

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability or for anything that
could expose personal data. Report it privately through GitHub's
**Security → Report a vulnerability** tab on this repository.

Include:

- a short description of the issue,
- steps to reproduce,
- affected file/endpoint,
- the impact you expect.

You will get an acknowledgement as soon as possible. Please give a reasonable
window to fix the issue before publishing details.

## Privacy model

Wardrobe is local-first:

- It runs on `127.0.0.1` by default and does not upload files.
- `config.toml`, `family.json`, `state/`, `reports/`, `demo_live/` and
  `demo_run/` are ignored by git.
- No API keys are stored in the repository. Use environment variables
  (`OPENAI_API_KEY`, etc.) if you enable a cloud LLM.
- Never commit a real `family.json`, inventory, scan report or move journal.
