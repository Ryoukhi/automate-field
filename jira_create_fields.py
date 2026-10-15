#!/usr/bin/env python3
"""
Jira Data Center - Création de définitions de champs personnalisés (Solution A)
Lit un fichier JSON et crée les champs personnalisés dans Jira DC via REST API.
Les options ne sont PAS ajoutées (limitation API DC) : elles sont exportées dans
un fichier annexe pour saisie manuelle via l'interface d'administration.
"""

import json
import os
import sys
import time
import logging
from typing import Optional, Dict, List, Any

import requests
from requests.auth import HTTPBasicAuth

# ========== Configuration ==========
JIRA_URL = os.getenv("JIRA_URL", "https://jira.dev.wassa-shared.com")
JIRA_USERNAME = os.getenv("JIRA_USERNAME", "")
JIRA_TOKEN = os.getenv("JIRA_TOKEN", "")
JIRA_PAT = os.getenv("JIRA_PAT", "")  # Optionnel : Personal Access Token

INPUT_FILE = "jira_fields.json"
OUTPUT_OPTIONS_FILE = "jira_fields_options.md"
LOG_FILE = "jira_field_creation.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, base_url: str, username: str = "", password: str = "", pat: str = ""):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Atlassian-Token": "nocheck",
        })
        if pat:
            self.session.headers["Authorization"] = f"Bearer {pat}"
            logger.info("Authentification : PAT")
        else:
            self.session.auth = HTTPBasicAuth(username, password)
            logger.info(f"Authentification : Basic ({username})")

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def request(self, method: str, path: str, **kwargs) -> Optional[requests.Response]:
        url = self._url(path)
        try:
            resp = self.session.request(method, url, timeout=30, **kwargs)
            if resp.status_code >= 400:
                logger.error(f"{method} {url} → {resp.status_code}: {resp.text[:500]}")
                return None
            return resp
        except requests.RequestException as e:
            logger.error(f"Erreur de requête {method} {url}: {e}")
            return None

    def get_field_id_by_name(self, name: str) -> Optional[str]:
        """Vérifie si un champ personnalisé du même nom existe déjà."""
        resp = self.request("GET", "/rest/api/2/field")
        if not resp:
            return None
        for field in resp.json():
            if field.get("name") == name and field.get("custom"):
                return field.get("id")
        return None

    def create_custom_field(self, name: str, field_type: str, searcher_key: str) -> Optional[Dict]:
        """
        POST /rest/api/2/field
        Crée la définition du champ personnalisé.
        """
        payload = {
            "name": name,
            "type": field_type,
            "searcherKey": searcher_key,
        }
        resp = self.request("POST", "/rest/api/2/field", json=payload)
        if resp:
            data = resp.json()
            logger.info(f"✅ Champ créé : {name} (id={data.get('id')})")
            return data
        return None


def load_field_definitions(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Le fichier JSON doit contenir un tableau d'objets")
    return data


def export_options_guide(fields: List[Dict[str, Any]], output_path: str):
    """
    Génère un guide Markdown listant, pour chaque champ, les options à saisir
    manuellement dans l'interface d'administration Jira.
    """
    lines = [
        "# Guide de saisie manuelle des options",
        "",
        "Pour chaque champ ci-dessous, rendez-vous dans :",
        "**Administration Jira → Problèmes → Champs personnalisés → [Champ] → Configurer → Modifier les options**",
        "",
        "---",
        "",
    ]
    for field in fields:
        lines.append(f"## {field['name']}")
        lines.append("")
        lines.append(f"- **Type** : `{field['type']}`")
        lines.append(f"- **Searcher** : `{field.get('searcherKey', '')}`")
        lines.append("")
        options = field.get("options", [])
        if options:
            lines.append("**Options à saisir :**")
            lines.append("")
            for opt in options:
                lines.append(f"- [ ] {opt}")
        else:
            lines.append("_Aucune option prédéfinie — champ à alimenter dynamiquement ou manuellement._")
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"📄 Guide des options exporté : {output_path}")


def main():
    if not os.path.exists(INPUT_FILE):
        logger.error(f"Fichier d'entrée introuvable : {INPUT_FILE}")
        sys.exit(1)

    if not JIRA_PAT and (not JIRA_USERNAME or not JIRA_TOKEN):
        logger.error("Veuillez définir JIRA_USERNAME/JIRA_TOKEN ou JIRA_PAT")
        sys.exit(1)

    client = JiraClient(JIRA_URL, JIRA_USERNAME, JIRA_TOKEN, JIRA_PAT)

    # Test de connexion
    test = client.request("GET", "/rest/api/2/myself")
    if not test:
        logger.error("❌ Échec de la connexion. Vérifiez l'URL, le nom d'utilisateur et le mot de passe.")
        sys.exit(1)
    logger.info(f"🔗 Connecté en tant que : {test.json().get('name')}")

    fields = load_field_definitions(INPUT_FILE)
    logger.info(f"📋 {len(fields)} définitions de champs à traiter")

    created, skipped, failed = 0, 0, 0

    for field_def in fields:
        name = field_def["name"]
        ftype = field_def["type"]
        searcher = field_def.get(
            "searcherKey",
            "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher"
        )

        # Vérifier l'existence
        existing_id = client.get_field_id_by_name(name)
        if existing_id:
            logger.info(f"⏭️  Champ déjà existant : {name} (id={existing_id}) — ignoré")
            skipped += 1
            continue

        # Créer le champ
        result = client.create_custom_field(name, ftype, searcher)
        if result:
            created += 1
        else:
            failed += 1

        time.sleep(0.5)  # Éviter le rate limiting

    # Générer le guide des options
    export_options_guide(fields, OUTPUT_OPTIONS_FILE)

    logger.info("=" * 60)
    logger.info(f"✅ Créés   : {created}")
    logger.info(f"⏭️  Ignorés : {skipped} (déjà existants)")
    logger.info(f"❌ Échecs   : {failed}")
    logger.info(f"📄 Guide des options : {OUTPUT_OPTIONS_FILE}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()