# Contributing to Avanguardia Publica

We welcome contributions to Avanguardia Publica! As a GPLv3 licensed project, we require that all contributions be provided under the same license.

## How to Contribute
1. Fork the repository.
2. Create a new branch for your feature or bugfix.
3. Add a Developer Certificate of Origin signoff to every commit (for example,
   `git commit --signoff -m "Describe the change"`). A cryptographic `-S` signature is
   optional and does not replace the DCO signoff.
4. Submit a Pull Request.

Database migrations are forward-only. Run `schema.sql` only for a brand-new database, then
apply each numbered migration once in order. Never replay the full migration directory on an
upgraded database; add a new repair migration instead.

## Code of Conduct
Please note that this project is released with a Contributor Code of Conduct. By participating in this project you agree to abide by its terms.
