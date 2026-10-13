<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/d/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Short firmware links

These links download the same firmware bytes as the original GitHub release,
with shorter filenames. Each link is pinned to one version and verified against
its SHA-256 checksum when the site is built. Existing links keep their original
firmware; a new release gets a new link.

<!-- firmware-shortlinks:table -->

For **RAK4631 Full Companion**, use the **UF2** for a bootloader-drive
drag-and-drop update. Use the **DFU ZIP** when pasting a custom download URL
into the Windows or Linux MeshCore firmware tool. The ZIP is the native
application update package, not the release's download bundle. These files do
not install a bootloader or SoftDevice.

The 1.17.1.10 preview2 files are for MeshTalk testing with Keymind Cascade and
USA Cascade defaults. The original release includes instructions, qualification
reports and checksums. See the [firmware picker](firmware_picker.md) for other
board and release choices.

## Adding links for another release

Add an entry to `docs/_data/firmware_shortlinks.json` with a unique,
version-specific filename, exact release tag and asset name, byte size, label
and SHA-256 checksum from the validated release. Keep the original firmware
extension. Never change or remove a published filename's version, source or
checksum. Labels can be corrected without changing the download.

The documentation build downloads and verifies the pinned files before
publishing them under `d/`. A missing asset, incorrect checksum or changed
published link stops deployment instead of publishing a different image.
