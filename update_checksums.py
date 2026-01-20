#!/usr/bin/env python3
import hashlib
import os
import re
import sys
from typing import Optional, Tuple


TRIPLE_RE = r'("""|\'\'\')'


def compute_checksum(body: str) -> str:
    """Retourne le SHA-256 hexadécimal du corps."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def find_header(text: str) -> Optional[Tuple[str, int, int, int, Optional[str]]]:
    """
    Détecte un header front-matter en début de fichier.

    Retourne un tuple:
      (kind, header_start, header_end, body_start, quote)

    - kind = "md" ou "py"
    - header_start/header_end délimitent le YAML (sans les lignes ---)
    - body_start = index où commence le corps
    - quote = délimiteur de docstring pour les .py (\""" ou \''') ou None
    """

    # 1) Markdown-style: --- ... --- en tout début de fichier
    m = re.match(r"^\ufeff?---\r?\n", text)
    if m:
        start = m.end()  # début réel du YAML
        m2 = re.search(r"^---\r?$", text[start:], flags=re.MULTILINE)
        if not m2:
            return None
        header_start = start
        header_end = start + m2.start()
        body_start = start + m2.end()
        return ("md", header_start, header_end, body_start, None)

    # 2) Python-style: docstring de tête avec front-matter YAML
    # Format attendu:
    #   """\n---\n<YAML>\n---\n"""\n<corps>
    m = re.match(rf"^\ufeff?(?P<quote>\"\"\"|\'\'\')\r?\n---\r?\n", text)
    if m:
        quote = m.group("quote")
        header_start = m.end()  # après la ligne '---' d'ouverture interne

        # cherche la ligne '---' de fermeture du YAML
        m2 = re.search(r"^---\r?$", text[header_start:], flags=re.MULTILINE)
        if not m2:
            return None
        header_end = header_start + m2.start()
        after = header_start + m2.end()

        # on s'attend à trouver: newline + triple-quote juste après
        m3 = re.match(r"\r?\n" + re.escape(quote), text[after:])
        if not m3:
            return None

        body_start = after + m3.end()
        return ("py", header_start, header_end, body_start, quote)

    return None


def update_header_block(header: str, checksum: str) -> str:
    """
    Met à jour ou ajoute la ligne 'checksum: ...' dans le bloc YAML.
    - header = contenu YAML sans les lignes ---.
    """
    # remplace n'importe quelle ligne existante commençant par 'checksum:'
    pat = re.compile(r"^(?P<k>checksum\s*:\s*)(?P<v>.*)$", re.MULTILINE)

    if pat.search(header):
        return pat.sub(lambda m: m.group("k") + checksum, header, count=1)

    # pas de checksum existant -> on l'ajoute à la fin
    if not header.endswith("\n"):
        header += "\n"
    return header + f"checksum: {checksum}\n"


def rewrite_text_with_checksum(text: str) -> str:
    """
    Si un header front-matter valide est trouvé, recalcule le checksum
    sur le corps et réécrit le header. Sinon, renvoie le texte inchangé.
    """
    info = find_header(text)
    if not info:
        return text

    kind, header_start, header_end, body_start, quote = info

    body = text[body_start:]
    checksum = compute_checksum(body)

    original_header = text[header_start:header_end]
    new_header = update_header_block(original_header, checksum)

    # reconstruction:
    # - Markdown: '---\n' + header + '---\n' + body
    # - Python:   '"""\\n---\\n' + header + '---\\n"""' + reste
    if kind == "md":
        # On suppose que le texte commence par '---\n', déjà vérifié par find_header
        before_header = text[:header_start]
        after_header = text[header_end:]
        return before_header + new_header + after_header

    if kind == "py":
        # Pour les .py, before_header contient '"""\\n---\\n'
        before_header = text[:header_start]
        after_header = text[header_end:]
        return before_header + new_header + after_header

    # fallback (ne devrait pas arriver)
    return text


def process_file(path: str) -> None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"[SKIP] {path}: impossible de lire le fichier ({e})")
        return

    updated = rewrite_text_with_checksum(original)

    if updated == original:
        print(f"[NO CHANGE] {path}")
        return

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"[UPDATED] {path}")
    except OSError as e:
        print(f"[ERROR] {path}: impossible d'écrire le fichier ({e})")


def iter_paths_from_args(args):
    if not args:
        # No arguments -> scan src/labscpi/rules/ by default
        rules_dir = os.path.join(os.path.dirname(__file__), "src", "labscpi", "rules")
        if os.path.isdir(rules_dir):
            args = [rules_dir]
        else:
            print(f"Error: Rules folder not found: {rules_dir}")
            return
    for p in args:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                # Ignore common folders
                dirs[:] = [d for d in dirs if d not in (".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules")]
                for name in files:
                    if name.endswith((".md", ".py")):
                        yield os.path.join(root, name)
        else:
            yield p


def main():
    paths = list(iter_paths_from_args(sys.argv[1:]))
    if not paths:
        print("No files to process.")
        return
    for path in paths:
        process_file(path)


if __name__ == "__main__":
    main()
