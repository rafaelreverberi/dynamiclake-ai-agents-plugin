# Releasing

1. Update `version` in `AIAgents.dynamiclakeplugin/plugin.json` and add a matching section to `CHANGELOG.md`.
2. Update the release ZIP name and link in `README.md`.
3. Run `PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_release.py` and check the ZIP and checksum in `dist/`.
4. Commit the tested source, then create and push an annotated `vX.Y.Z` tag.
5. Create a private GitHub release from that tag. Attach the ZIP and `.zip.sha256` file from `dist/`.
6. Check that the repository remains private, both assets are present, the release tag points at the tested commit, and the CI run passed.

The GitHub-generated source archives do not contain an installable `.dynamiclakeplugin` folder ready for DynamicLake's **Install Local** flow. Download, extract, and select the plugin folder from the attached ZIP.
