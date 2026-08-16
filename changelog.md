Mnemos-Frontend
- None

Mnemos-Backend
- UID format mismatch between pgvector (returns canonical 36-char dashed UUIDs) and SQLite (stores 32-char compact UUIDs). Fixed by stripping dashes from values stored in pgvector

General
- Update changelog to fix restrictive Rockchip NPU binding

Notes
- Fixes issue related to Rockchip variant correctly detecting faces but failing to identify