# Security policy

Fresh MCPE handles local files and launches another program. Report a security concern privately through GitHub's security reporting feature if available for this repository, rather than publishing exploit details in an issue.

## Safety boundaries

- Do not enter Microsoft or Google passwords into Fresh MCPE.
- Import native launcher mods only from sources you trust. Native code is not sandboxed by this app.
- Archive extraction rejects path traversal and archive symlinks, and limits imports to 1 GiB expanded size and 25,000 entries.
- World backup folders may contain private world data; do not upload them to GitHub.
- Fresh MCPE does not download or bundle the Minecraft runtime.
