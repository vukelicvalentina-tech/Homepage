#!/usr/bin/env python3
"""Rebuild the exported bundle from an updated .dc.html source.

The exporter applies three transforms to the authoring source; we reproduce
them so a source edit can be published without re-running the editor:

  1. camelCase attributes  ->  sc-camel-<kebab>
  2. <helmet> Google-Fonts link -> inlined @font-face with UUID refs
     (fonts are unchanged, so the previous helmet is reused verbatim)
  3. image src expression -> resolved from window.__resources with the
     original expression as fallback

The exporter also hardcodes the page title, so we override it here.
"""
import html
import json
import re
import sys

TEMPLATE_OPEN = '<script type="__bundler/template">'
PAGE_TITLE = 'Valentina Vukelic — Portfolio'


def kebab(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()


def camel_attrs_to_sc(markup):
    def repl(m):
        return '%ssc-camel-%s=' % (m.group(1), kebab(m.group(2)))
    return re.sub(r'(\s)([a-z]+(?:[A-Z][a-zA-Z0-9]*)+)\s*=', repl, markup)


def rewrite_image_src(script):
    """src: '<expr>'  ->  src: (window.__resources && ...) || ('<expr>')"""
    pattern = re.compile(
        r"(\bsrc:\s*)('https://picsum\.photos/seed/vv'[^,\n]*?)(,\s*\n)")
    matches = pattern.findall(script)
    if len(matches) != 1:
        sys.exit('expected exactly 1 image src expression, found %d' % len(matches))
    return pattern.sub(
        r"\1(window.__resources && window.__resources['img' + i]) || (\2)\3",
        script)


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

    # --- body: everything between </helmet> and </x-dc> ---
    new_body = re.search(r'</helmet>(.*?)</x-dc>', source, re.S).group(1)
    new_body = camel_attrs_to_sc(new_body)
    template, n = re.subn(r'(</helmet>).*?(</x-dc>)',
                          lambda m: m.group(1) + new_body + m.group(2),
                          template, count=1, flags=re.S)
    if n != 1:
        sys.exit('body region not found in template')

    # --- script: the whole <script type="text/x-dc"> element ---
    new_script = re.search(r'<script type="text/x-dc".*?</script>', source, re.S).group(0)
    new_script = rewrite_image_src(new_script)
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
    print('wrote %s' % out_path)


if __name__ == '__main__':
    main(*sys.argv[1:4])
