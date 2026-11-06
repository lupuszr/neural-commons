#!/usr/bin/env python3
"""Attach a description and manifest-backed photos to an existing research record.

Files are copied to the participant artifact store, never served from local paths.
Existing records are retained; repeated identical imports are idempotent.
"""
import argparse
import hashlib
import json
from pathlib import Path

from research_tracker import Tracker


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def event_id(prefix, data):
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return prefix + '-' + hashlib.sha256(encoded).hexdigest()[:32]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True)
    parser.add_argument('--experiment', required=True)
    parser.add_argument('--description', type=Path, help='JSON description object')
    parser.add_argument('--manifest', type=Path, help='JSON with rows containing image paths and SHA-256 identities')
    args = parser.parse_args()
    if not args.description and not args.manifest:
        parser.error('Provide --description or --manifest.')
    tracker = Tracker(args.home, args.experiment)
    prepared = []
    if args.manifest:
        manifest = json.loads(args.manifest.read_text())
        for row in manifest['rows']:
            path = Path(row['image'])
            if not path.is_absolute():
                path = args.manifest.resolve().parent / path
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('Image exceeds attachment limit: ' + str(path))
            identity = digest(path)
            if identity != row['sha256']:
                raise ValueError('Image does not match committed manifest: ' + str(path))
            split = row.get('split', '')
            display_split = {'b_development': 'development', 'a_development': 'development',
                             'b_selection': 'selection', 'a_selection': 'selection'}.get(split, split)
            filename = path.name
            caption = row.get('label', 'Photo').replace('_', ' ').capitalize()
            if row.get('camera') is not None:
                caption += ' · camera ' + str(row['camera'])
            source = manifest.get('source')
            metadata = dict(artifact=identity, label=filename, filename=filename, kind='image',
                            split=display_split, original_split=split, target_label=row.get('label', ''),
                            caption=caption, source=row.get('source', ''), source_label=row.get('source_label', ''),
                            source_file=row.get('name', ''), license=manifest.get('license', ''),
                            bytes=path.stat().st_size)
            if isinstance(source, str) and source.startswith(('https://', 'http://')):
                metadata['source_url'] = source
            prepared.append((metadata, dict(label=filename, path=str(path.resolve()))))
    # Validate every file before committing any of this import's notes.
    if args.description:
        description = json.loads(args.description.read_text())
        if not isinstance(description, dict):
            raise ValueError('Description must be a JSON object.')
        data = dict(description=description)
        tracker.record('note', data, evidence=[args.description], event_id=event_id('description', data))
    for start in range(0, len(prepared), 48):
        batch = prepared[start:start + 48]
        data = dict(summary='Attached source photographs for the experiment asset library.',
                    manifest_sha256=digest(args.manifest), assets=[m for m, _ in batch])
        tracker.record('note', data, evidence=[a for _, a in batch], event_id=event_id('photo-assets', data))
    print(json.dumps(dict(experiment=args.experiment, photos=len(prepared),
                          description_attached=bool(args.description))))


if __name__ == '__main__':
    main()
