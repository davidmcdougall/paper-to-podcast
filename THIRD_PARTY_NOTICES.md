# Third-party notices

The MIT license in this repository covers original application code, not independent dependencies, input papers, voices, or user-supplied artwork. Dependencies retain their own notices and terms.

Direct core dependencies, verified from the installed distributions:

| Dependency | License |
|---|---|
| Flask | BSD-3-Clause |
| python-dotenv | BSD-3-Clause |
| pypdf | BSD-3-Clause |
| Anthropic Python SDK | MIT |
| ElevenLabs Python SDK | MIT |
| boto3 | Apache-2.0 |
| TinyTag | MIT |
| filelock | MIT |

Transitive dependencies retain their own notices in their installed distributions. In particular, Certifi uses MPL-2.0 (file-level copyleft); the other inspected transitive runtime licenses are MIT, BSD, Apache-2.0, PSF-2.0 or combinations of those licenses. Retain those notices when redistributing dependencies; this inventory does not replace their license texts. pytest and its development dependencies are not required to run the app.

Earlier revisions used PyMuPDF (AGPL/commercial) and Mutagen (GPL-2.0-or-later). Those dependencies are not installed by the current requirements. Their respective obligations still matter if you use or redistribute those earlier versions. The repository's MIT license never relicensed them.

Optional transcription uses openai-whisper (MIT), with separately installed model/runtime dependencies and FFmpeg. FFmpeg licensing varies with its build (LGPL/GPL); consult the build you distribute. This optional stack is not included in the core constraints/license inventory.

Anthropic, ElevenLabs and Cloudflare are services governed by their own terms and prices. A software license does not grant publication rights over academic papers, voices or artwork.

The current SVG favicon was authored as part of this project's hardening changes and is covered by MIT. Earlier raster favicon provenance was not documented; those files were removed from the current tree, not from history. The maintainer must establish rights or arrange appropriate removal if those historical assets were not theirs to publish.
