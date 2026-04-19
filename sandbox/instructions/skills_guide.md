## Skills System

Skills are custom instruction files that extend your capabilities.

### Adding a skill
When the user says something like "learn this skill" or "add a skill for X":
1. Ask for a name and description if not provided
2. Create `instructions/skills/<skill-name>.md` with the instructions
3. Confirm the skill was saved

### Using a skill
Before handling any request, check `instructions/skills/` for a relevant file.
If one exists, read it and follow those instructions.

### Listing skills
When asked to list skills, list files in `instructions/skills/`.

