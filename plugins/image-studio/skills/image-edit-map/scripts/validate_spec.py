#!/usr/bin/env python3
"""Validate structure and cross-references; does not verify visual accuracy.

Requires Python 3 and jsonschema. Usage: python validate_spec.py image-spec.json
"""
import json
import sys
import argparse
from pathlib import Path


def validate(data, schema):
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(schema)
    errors = [f"{'.'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
              for e in Draft202012Validator(schema).iter_errors(data)]
    if errors:
        return errors
    images = {x['id']: x for x in data['images']}
    sections = {x['id']: x for x in data['sections']}
    elements = {x['id']: x for x in data['elements']}
    ids = [x['id'] for kind in ('images', 'sections', 'elements', 'relationships')
           for x in data[kind]]
    if len(ids) != len(set(ids)):
        errors.append('IDs must be unique across images, sections, elements, relationships.')
    numbers = set()
    for kind in ('sections', 'elements'):
        for item in data[kind]:
            prefix = item['id']
            if item['image_id'] not in images:
                errors.append(f'{prefix}: unknown image_id')
            x, y, w, h = item['bbox']
            if w <= 0 or h <= 0 or x + w > 1.000000001 or y + h > 1.000000001:
                errors.append(f'{prefix}: bounding box must have area and fit within the source image')
            if kind == 'elements':
                section = sections.get(item['section_id'])
                if not section or section['image_id'] != item['image_id']:
                    errors.append(f'{prefix}: section must belong to the same image')
                key = (item['image_id'], item['number'])
                if prefix != f"{item['image_id']}:{item['number']}":
                    errors.append(f"{prefix}: id must be {item['image_id']}:{item['number']} (image_id:number)")
                if key in numbers:
                    errors.append(f'{prefix}: duplicate display number in image')
                numbers.add(key)
                ax, ay = item['anchor']
                if not (x <= ax <= x+w and y <= ay <= y+h):
                    errors.append(f'{prefix}: arrow target must fall inside the element bounds')
    for relation in data['relationships']:
        if relation['image_id'] not in images:
            errors.append(f"{relation['id']}: unknown relationship image")
        for key in ('from_id', 'to_id'):
            endpoint = relation[key]
            if endpoint is not None:
                item = elements.get(endpoint)
                if not item or item['image_id'] != relation['image_id']:
                    errors.append(f"{relation['id']}: {key} must reference an element in the same image")
            elif not relation['note'].strip():
                errors.append(f"{relation['id']}: unknown endpoint needs an explanatory note")
    categories = ('picture_types', 'composition', 'text_content', 'typography',
                  'palette', 'color_grading', 'lighting', 'materials', 'layers',
                  'preservation', 'export', 'unknowns')
    for category in categories:
        for record in data[category]:
            if record['target_id'] not in images and record['target_id'] not in elements:
                errors.append(f"{category}: unknown target_id {record['target_id']}")
    if data['mode'] == 'reverse_engineer':
        covered = {x['target_id'] for x in data['picture_types']}
        for image_id in images:
            if image_id not in covered:
                errors.append(f'{image_id}: reverse-engineering needs a picture-type record')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('--image', type=Path, help='Cross-check reported width/height against a decoded image (requires Pillow)')
    parser.add_argument('--image-id', help='Image ID for --image in a multiple-image specification')
    args = parser.parse_args()
    schema_path = Path(__file__).resolve().parents[1] / 'references/image-spec.schema.json'
    try:
        def reject_constant(value):
            raise ValueError(f'Non-JSON constant {value} is not allowed')

        def unique_keys(pairs):
            keys = [key for key, _ in pairs]
            if len(keys) != len(set(keys)):
                raise ValueError(f'Duplicate JSON keys: {sorted({k for k in keys if keys.count(k) > 1})}')
            return dict(pairs)
        if args.image_id and not args.image:
            raise ValueError('--image-id needs --image')
        try:
            data = json.loads(args.spec.read_text(encoding='utf-8-sig'), parse_constant=reject_constant, object_pairs_hook=unique_keys)
        except RecursionError:
            raise ValueError('JSON nesting is too deep')
        schema = json.loads(schema_path.read_text(encoding='utf-8-sig'))
        try:
            errors = validate(data, schema)
        except RecursionError:
            raise ValueError('JSON nesting is too deep')
        if args.image and not errors:
            from PIL import Image, ImageOps
            selected = [x for x in data['images'] if x['id'] == args.image_id] if args.image_id else data['images']
            if len(selected) != 1:
                errors.append('Select exactly one image with --image-id for metadata verification.')
            else:
                try:
                    with Image.open(args.image) as opened:
                        im = ImageOps.exif_transpose(opened)  # compare displayed dimensions
                        for key, actual in [('width_px', im.width), ('height_px', im.height)]:
                            claim = selected[0]['metadata'].get(key, {}).get('value')
                            if claim is not None and (type(claim) is not int or claim != actual):
                                errors.append(f'{key}: extracted value {claim} differs from decoded file {actual}')
                except Image.DecompressionBombError as exc:
                    raise ValueError(f'Image is too large to verify safely: {exc}')
    except ImportError:
        print('Missing dependency: install jsonschema, and Pillow when using --image.', file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print('PASS: schema, geometry, IDs, and cross-references'+('; reported dimensions match decoded image' if args.image else '')+'. Visual accuracy not checked.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
