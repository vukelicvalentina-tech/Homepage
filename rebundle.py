#!/usr/bin/env python3
"""Rebuild the exported bundle from an updated .dc.html source.

Claude Design's export ships two things: the editable source
(``Valentina Vukelic.dc.html``) and a bundled page that inlines every
asset. Editing the source does not necessarily refresh the bundle, so the
published page can lag behind the design. This script applies the
exporter's transforms itself, so a source edit can be published without
waiting for a fresh export:

  1. camelCase attributes  ->  sc-camel-<kebab>
  2. the Google-Fonts <link> -> inlined @font-face rules pointing at the
     font files already in the bundle's manifest
  3. image src expression -> resolved from window.__resources with the
     original expression as fallback

Everything heavy (the asset manifest, the bundler runtime) is carried
over from the previous bundle untouched; only markup and script are
replaced. The exporter also hardcodes the page title, so we override it.

Usage:
    python3 rebundle.py <old-bundle.html> <source.dc.html> <out.html>
"""
import html
import json
import re
import sys

TEMPLATE_OPEN = '<script type="__bundler/template">'
PAGE_TITLE = 'Valentina Vukelic — Portfolio'

FONT_FACE_TEMPLATE = """/* %(subset)s */
@font-face {
  font-family: %(family)s;
  font-style: normal;
  font-weight: %(weight)s;
  font-stretch: 100%%;
  font-display: swap;
  src: url("%(uuid)s") format('woff2');
  unicode-range: %(unicode_range)s;
}"""


def kebab(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()


def camel_attrs_to_sc(markup):
    """onMouseMove="..." -> sc-camel-on-mouse-move="..."."""
    return re.sub(r'(\s)([a-z]+(?:[A-Z][a-zA-Z0-9]*)+)\s*=',
                  lambda m: '%ssc-camel-%s=' % (m.group(1), kebab(m.group(2))),
                  markup)


def rewrite_image_src(script):
    """Resolve image sources from the bundle manifest, keeping a fallback.

    Idempotent: a source that already carries the rewrite (because it was
    round-tripped through a previous export) is returned unchanged.
    """
    already = re.search(r'\bsrc:\s*\(window\.__resources\b', script)
    if already:
        return script
    pattern = re.compile(r"(\bsrc:\s*)('https://picsum\.photos/[^,\n]*?)(,\s*\n)")
    hits = pattern.findall(script)
    if len(hits) != 1:
        sys.exit('expected exactly 1 image src expression, found %d' % len(hits))
    return pattern.sub(
        r"\1(window.__resources && window.__resources['img' + i]) || (\2)\3",
        script)


def helmet_of(markup):
    return re.search(r'<helmet.*?</helmet>', markup, re.S).group(0)


def font_subsets(old_helmet):
    """Extract one (subset, family, uuid, unicode-range) per charset subset.

    Google serves a single variable-weight file per subset and repeats it
    across the requested weights, so deduplicating by uuid yields exactly
    the distinct font files the manifest holds.
    """
    rules = re.findall(
        r'/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}', old_helmet, re.S)
    subsets, seen = [], set()
    for subset, block in rules:
        uuid = re.search(r'url\("([^"]+)"\)', block).group(1)
        if uuid in seen:
            continue
        seen.add(uuid)
        subsets.append({
            'subset': subset,
            'family': re.search(r'font-family:\s*([^;]+);', block).group(1).strip(),
            'uuid': uuid,
            'unicode_range': re.search(r'unicode-range:\s*([^;]+);', block).group(1).strip(),
        })
    if not subsets:
        sys.exit('no @font-face rules found in the previous bundle')
    return subsets


def requested_weights(source_helmet):
    link = re.search(r'fonts\.googleapis\.com/css2\?[^"\']+', source_helmet)
    if not link:
        return None
    spec = html.unescape(link.group(0))
    m = re.search(r'wght@([\d;]+)', spec)
    return [w for w in m.group(1).split(';') if w] if m else ['400']


def build_helmet(source_helmet, subsets, weights):
    """Source helmet with the Google-Fonts stylesheet link inlined."""
    css = '\n'.join(
        FONT_FACE_TEMPLATE % dict(s, weight=w) for w in weights for s in subsets)
    new, n = re.subn(r'<link[^>]*fonts\.googleapis\.com/css2[^>]*>',
                     lambda m: '<style>%s\n</style>' % css,
                     source_helmet, count=1)
    if n != 1:
        sys.exit('Google-Fonts stylesheet link not found in source helmet')
    return new


def split_template(bundle):
    start = bundle.index(TEMPLATE_OPEN) + len(TEMPLATE_OPEN)
    end = bundle.rindex('</script>')
    return bundle[:start], bundle[start:end], bundle[end:]


def encode_template(text):
    # json.dumps leaves '/' bare; the exporter escapes '</' so an inner
    # </script> cannot terminate the surrounding <script> element.
    return '\n' + json.dumps(text, ensure_ascii=False).replace('</', '<\\/') + '\n'


def main(bundle_path, source_path, out_path):
    bundle = open(bundle_path, encoding='utf-8').read()
    source = open(source_path, encoding='utf-8').read()

    prefix, template_json, suffix = split_template(bundle)
    template = json.loads(template_json.strip())

    # --- <x-dc>: helmet rebuilt from source, body attribute-transformed ---
    source_helmet = helmet_of(source)
    weights = requested_weights(source_helmet)
    if weights:
        source_helmet = build_helmet(
            source_helmet, font_subsets(helmet_of(template)), weights)
    body = re.search(r'</helmet>(.*?)</x-dc>', source, re.S).group(1)
    new_xdc = source_helmet + camel_attrs_to_sc(body)
    template, n = re.subn(r'(<x-dc>).*?(</x-dc>)',
                          lambda m: m.group(1) + '\n' + new_xdc + m.group(2),
                          template, count=1, flags=re.S)
    if n != 1:
        sys.exit('<x-dc> region not found in template')

    # --- script: the whole <script type="text/x-dc"> element ---
    new_script = rewrite_image_src(
        re.search(r'<script type="text/x-dc".*?</script>', source, re.S).group(0))
    template, n = re.subn(r'<script type="text/x-dc".*?</script>',
                          lambda m: new_script,
                          template, count=1, flags=re.S)
    if n != 1:
        sys.exit('x-dc script not found in template')

    # --- page title: the exporter always emits "Bundled Page" ---
    prefix, n = re.subn(r'<title>.*?</title>',
                        '<title>%s</title>' % html.escape(PAGE_TITLE),
                        prefix, count=1, flags=re.S)
    if n != 1:
        sys.exit('<title> not found in bundle head')

    open(out_path, 'w', encoding='utf-8').write(
        prefix + encode_template(template) + suffix)
    print('wrote %s (fonts: %s)' % (out_path, ', '.join(weights or ['unchanged'])))


if __name__ == '__main__':
    main(*sys.argv[1:4])
