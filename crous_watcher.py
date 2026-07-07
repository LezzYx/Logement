#!/usr/bin/env python3
"""
Surveille une recherche filtrée sur trouverunlogement.lescrous.fr
et envoie une notification Discord dès qu'un nouveau logement apparaît.

Configuration via variables d'environnement (voir README.md) :
  SEARCH_URL      -> URL de recherche déjà filtrée (ville, prix, type...)
  DISCORD_WEBHOOK -> URL du webhook Discord
  MAX_PAGES       -> nombre max de pages à parcourir (défaut 5)
"""

import os
import sys
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

SEARCH_URL = os.environ.get("SEARCH_URL", "").strip()
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
MAX_PAGES = int(os.environ.get("MAX_PAGES", "5"))
STATE_FILE = os.environ.get("STATE_FILE", "seen_ids.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def set_page(url: str, page: int) -> str:
    """Ajoute/replace le paramètre page= dans l'URL de recherche."""
    parts = urlparse(url)
    query = parse_qs(parts.query)
    query["page"] = [str(page)]
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))


def fetch_listings(url: str):
    """Récupère les logements (id, titre, ville, prix, lien, mentions) d'une page."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    listings = []
    # Chaque logement est un lien vers /tools/<id_outil>/accommodations/<id>
    for link in soup.select('a[href*="/accommodations/"]'):
        href = link.get("href", "")
        if "/accommodations/" not in href:
            continue
        full_url = urljoin(url, href)
        acc_id = full_url.rstrip("/").split("/")[-1]
        if not acc_id.isdigit():
            continue

        title = link.get_text(strip=True)
        # Le conteneur parent contient prix / ville / mentions (dernières places, etc.)
        container = link.find_parent("li") or link.find_parent("div") or link
        text = container.get_text(" ", strip=True)

        listings.append({
            "id": acc_id,
            "title": title,
            "url": full_url,
            "text": text,
        })

    # Nombre total de résultats (pour info / logs), si présent dans le titre de page
    total = None
    if soup.title:
        pass
    return listings


def fetch_all_listings(base_url: str, max_pages: int):
    all_listings = {}
    for page in range(1, max_pages + 1):
        page_url = set_page(base_url, page)
        # Les erreurs réseau/HTTP remontent volontairement (pas de try/except
        # ici) : elles doivent être traitées comme une panne par main(), pas
        # comme "fin de pagination".
        listings = fetch_listings(page_url)

        if not listings:
            break

        for item in listings:
            all_listings[item["id"]] = item

        time.sleep(1)  # petite pause polie entre pages
    return all_listings


def load_seen_ids(path: str) -> set:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()


def save_seen_ids(path: str, ids: set):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


STATUS_FILE = os.environ.get("STATUS_FILE", "status.json")
ERROR_THRESHOLD = int(os.environ.get("ERROR_THRESHOLD", "3"))  # ~15 min à 5 min/run


def load_status(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {"consecutive_errors": 0, "alerted": False}


def save_status(path: str, status: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def notify_error(webhook_url: str, message: str):
    embed = {
        "title": "⚠️ Crous Watcher : problème détecté",
        "description": message,
        "color": 15548997,  # rouge
    }
    try:
        r = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[!] Échec envoi alerte d'erreur Discord: {e}", file=sys.stderr)


def notify_recovery(webhook_url: str):
    embed = {
        "title": "✅ Crous Watcher : retour à la normale",
        "description": "Le site est de nouveau accessible, la surveillance a repris normalement.",
        "color": 3066993,  # vert
    }
    try:
        r = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[!] Échec envoi alerte de reprise Discord: {e}", file=sys.stderr)


import re

SURFACE_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*m²")
PRICE_RE = re.compile(r"(\d{2,4}(?:[.,]\d+)?)\s*€")


def fetch_detail(url: str) -> dict:
    """Va chercher des infos complémentaires (surface, adresse, prix) sur la
    fiche détaillée du logement. Les sélecteurs sont génériques (regex sur le
    texte) car la structure exacte des balises n'a pas pu être vérifiée --
    à affiner une fois le site accessible."""
    details = {}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        m = SURFACE_RE.search(text)
        if m:
            details["surface"] = f"{m.group(1)} m²"

        m = PRICE_RE.search(text)
        if m:
            details["price"] = f"{m.group(1)} €"

        # Heuristique adresse : ligne contenant un code postal français
        addr_match = re.search(r"[\w'’\-, ]{3,80}\b\d{5}\b[\w'’\-, ]{0,40}", text)
        if addr_match:
            details["address"] = addr_match.group(0).strip()

    except requests.RequestException as e:
        print(f"[!] Impossible de récupérer le détail ({url}): {e}", file=sys.stderr)

    return details


def notify_discord(webhook_url: str, item: dict):
    details = fetch_detail(item["url"])

    fields = []
    if details.get("price"):
        fields.append({"name": "Loyer", "value": details["price"], "inline": True})
    if details.get("surface"):
        fields.append({"name": "Surface", "value": details["surface"], "inline": True})
    if details.get("address"):
        fields.append({"name": "Adresse", "value": details["address"], "inline": False})

    embed = {
        "title": f"🏠 Nouveau logement disponible : {item['title']}",
        "url": item["url"],
        "description": item["text"][:300],
        "fields": fields,
        "color": 5763719,
    }

    payload = {"embeds": [embed]}
    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[!] Échec envoi Discord: {e}", file=sys.stderr)


def main():
    if not SEARCH_URL:
        print("[!] SEARCH_URL non défini.", file=sys.stderr)
        sys.exit(1)
    if not DISCORD_WEBHOOK:
        print("[!] DISCORD_WEBHOOK non défini.", file=sys.stderr)
        sys.exit(1)

    status = load_status(STATUS_FILE)

    try:
        seen_ids = load_seen_ids(STATE_FILE)
        first_run = len(seen_ids) == 0

        current = fetch_all_listings(SEARCH_URL, MAX_PAGES)
        current_ids = set(current.keys())

        new_ids = current_ids - seen_ids
        print(f"[i] {len(current_ids)} logements trouvés, {len(new_ids)} nouveaux.")

        if first_run:
            print("[i] Premier lancement : initialisation sans notification.")
        else:
            for acc_id in new_ids:
                notify_discord(DISCORD_WEBHOOK, current[acc_id])

        save_seen_ids(STATE_FILE, current_ids)

    except Exception as e:
        # Panne réseau, erreur HTTP, changement de structure HTML, etc.
        status["consecutive_errors"] = status.get("consecutive_errors", 0) + 1
        print(f"[!] Erreur ({status['consecutive_errors']} consécutive(s)): {e}", file=sys.stderr)

        if status["consecutive_errors"] >= ERROR_THRESHOLD and not status.get("alerted"):
            notify_error(
                DISCORD_WEBHOOK,
                f"Le bot rencontre des erreurs répétées depuis {ERROR_THRESHOLD} cycles "
                f"(~{ERROR_THRESHOLD * 5} min).\nDernière erreur : `{e}`\n\n"
                f"Site indisponible, structure de page changée, ou bug — "
                f"va voir les logs GitHub Actions pour le détail, et reviens "
                f"vers Claude avec l'erreur pour la corriger.",
            )
            status["alerted"] = True

        save_status(STATUS_FILE, status)
        sys.exit(1)  # fait apparaître le run en échec (rouge) dans GitHub Actions

    else:
        # Cycle réussi : si on sortait d'une panne, prévenir que c'est rétabli
        if status.get("alerted"):
            notify_recovery(DISCORD_WEBHOOK)
        status["consecutive_errors"] = 0
        status["alerted"] = False
        save_status(STATUS_FILE, status)


if __name__ == "__main__":
    main()
