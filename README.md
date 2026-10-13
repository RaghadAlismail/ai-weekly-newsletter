# AI Weekly Newsletter

Enter exactly ten URLs to create a private Arabic newsletter draft. Optional source text and images supplement automatic extraction.

The app generates PowerPoint using the protected Arabic template, then enforces sequential owner, content-reviewer, designer, and final-reviewer approvals. Edits preserve revision history and invalidate downstream approvals. Final approval locks the master without making it public.

Required runtime settings: DATABASE_URL, FLASK_SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, AUTHORIZED_USERS_JSON, NEWSLETTER_TEMPLATE_KEY, OPENAI_API_KEY. OPENAI_MODEL selects the generation model. Never commit these settings. The template is encrypted; its key is stored only in Render.

Google publishing requires each editor's explicit connection from the workspace and the Google Drive API enabled on the OAuth project. Tokens are encrypted in PostgreSQL. Exports create private Google Slides/Docs copies.

Reviewers must be authorized users before they can be assigned. Free Render PostgreSQL expires after 30 days. Images, draft decks, and revisions persist in PostgreSQL within that lifetime.
