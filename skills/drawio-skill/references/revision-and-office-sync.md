# Revising User-Edited Diagrams

Use this workflow when the user edits an existing `.drawio`, requests layout corrections, or asks to synchronize the approved flowchart into Word or PowerPoint.

## Protect the Editable Source

1. Resolve the exact `.drawio` path and inspect its timestamp before acting. Do not infer the source from a screenshot or a stale PNG.
2. Treat the newest user-edited `.drawio` as authoritative. Do not call a builder that recreates the diagram as an intermediate step.
3. If one script combines `build_drawio()` with document generation, invoke only its document functions or create a targeted synchronization path.
4. Preserve the source file's timestamp or hash when only exports and downstream documents need changes.
5. Write revised Word/PPT files to new names unless the user explicitly requests overwrite.

On Windows PowerShell 5, `Get-Content` may decode UTF-8 XML as the ANSI code page and display Chinese text as mojibake. Read XML with an explicit UTF-8 decoder or a structured parser:

```powershell
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$xml = New-Object System.Xml.XmlDocument
$xml.LoadXml($text)
```

Never save text that was read through a lossy or incorrect decoder.

## Edit Swimlanes Correctly

- Child geometry is relative to its parent swimlane. Moving the swimlane moves all child nodes; do not also apply the same offset to every child.
- Keep edges between nodes in one lane under that lane when appropriate. Keep cross-lane edges at the page root and use page-coordinate waypoints.
- When moving the whole process upward, move the top-level lanes and page-level objects first. Recalculate page height only after every child, connector, label, and legend remains inside the canvas.
- Leave a visible gap between the last process node, the lane boundary, and the legend. Do not use the legend band as an edge-routing corridor.

## Prevent Connector Overlap

1. Route the primary process as a solid line and secondary/downstream associations as dashed lines with a distinct, restrained color.
2. Do not use a dashed style to hide coincident paths. Separate the paths with explicit waypoints first; use dashes to communicate secondary semantics.
3. Pin `exitX`/`exitY` and `entryX`/`entryY` when a node has multiple connections.
4. Split outgoing paths across different sides. A reliable bottom-flow pattern is: primary continuation exits left, downstream query exits right.
5. Route long cross-lane associations through an empty outer corridor, usually above or below the main node field.
6. Keep the final straight segment before an arrowhead long enough to remain legible.
7. Re-export and visually trace every path after moving nodes; XML validation cannot detect all visual crossings.

Use solid black for the main sequence and a purple dashed line for downstream/reference relationships only when that matches the diagram's legend. Preserve the user's established visual grammar when one exists.

## Export From the Approved Source

1. Run `validate.py` against the current `.drawio`.
2. Export a preview PNG without `-e` and inspect labels, paths, bottom spacing, and the legend.
3. Export the final embedded PNG from the same `.drawio`, then run `repair_png.py`.
4. Do not regenerate the source between preview and final export.

## Synchronize Word and PowerPoint

Before editing downstream documents, extract a small change manifest from the `.drawio`: changed node labels, transaction/report identifiers, lane names, and downstream relationships.

- Replace the embedded diagram with the freshly exported PNG, not an older file with the same name.
- Update surrounding Word node tables, role descriptions, test cases, and PPT key-node summaries wherever changed labels appear.
- Preserve the image aspect ratio. In Word, keep the existing width and recompute height. In PowerPoint, retain the intended picture box and fit the new image without stretching.
- Preserve the original document/deck and produce a clearly named revision when files may be open or locked.
- Use the Word and PowerPoint skills for package inspection and render validation.

## Final Consistency Checks

- `validate.py` reports zero errors; review warnings before accepting them.
- The preview visibly matches the user's edited `.drawio`.
- The editable source was not overwritten during export or document generation.
- Word/PPT contain the current image; compare the embedded media hash with the exported PNG when practical.
- Changed labels appear consistently in the diagram, Word tables/body text, PPT flow page, implementation list, and test notes.
- Word/PPT image dimensions preserve the source aspect ratio.
