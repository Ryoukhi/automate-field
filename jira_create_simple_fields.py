#!/usr/bin/env python3
"""
Jira Data Center - Création de champs simples (Text, Date, Numeric, Radio, Checkbox)
Lit un fichier JSON et crée les définitions de champs dans Jira DC via REST API.
Les options des Radio/Checkbox ne sont PAS ajoutées (limitation API DC) :
elles sont exportées dans un guide Markdown pour saisie manuelle.
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
JIRA_PAT = os.getenv("JIRA_PAT", "")  # Optionnel

INPUT_FILE = "jira_simple_fields.json"
OUTPUT_GUIDE = "jira_simple_fields_options.md"
LOG_FILE = "jira_simple_fields_creation.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# Mapping type JSON → type Jira + option à saisir manuellement
FIELD_TYPES = {
    "text": "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
    "textarea": "com.atlassian.jira.plugin.system.customfieldtypes:textarea",
    "number": "com.atlassian.jira.plugin.system.customfieldtypes:float",
    "date": "com.atlassian.jira.plugin.system.customfieldtypes:datepicker",
    "radio": "com.atlassian.jira.plugin.system.customfieldtypes:radiobuttons",
    "checkbox": "com.atlassian.jira.plugin.system.customfieldtypes:checkbox",
}

SEARCHER_TYPES = {
    "text": "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    "textarea": "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    "number": "com.atlassian.jira.plugin.system.customfieldtypes:exactnumber",
    "date": "com.atlassian.jira.plugin.system.customfieldtypes:daterange",
    "radio": "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
    "checkbox": "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
}


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

    def request(self, method: str, path: str, **kwargs) -> Optional[requests.Response]:
        url = f"{self.base_url}{path}"
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
        resp = self.request("GET", "/rest/api/2/field")
        if not resp:
            return None
        for field in resp.json():
            if field.get("name") == name and field.get("custom"):
                return field.get("id")
        return None

    def create_custom_field(self, name: str, field_type: str, searcher_key: str) -> Optional[Dict]:
        payload = {
            "name": name,
            "type": field_type,
            "searcherKey": searcher_key,
        }
        resp = self.request("POST", "/rest/api/2/field", json=payload)
        if resp:
            data = resp.json()
            logger.info(f"✅ Champ créé : {name} (id={data.get('id')}, type={field_type})")
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
    Génère un guide Markdown pour les champs Radio/Checkbox dont les options
    doivent être saisies manuellement dans Jira.
    """
    lines = [
        "# Guide de saisie manuelle des options",
        "",
        "Champs Radio/Checkbox dont les options sont à saisir manuellement :",
        "**Administration Jira → Problèmes → Champs personnalisés → [Champ] → Configurer → Modifier les options**",
        "",
        "---",
        "",
    ]
    count = 0
    for field in fields:
        ftype = field.get("type", "")
        if ftype in ("radio", "checkbox"):
            count += 1
            lines.append(f"## {field['name']}")
            lines.append("")
            lines.append(f"- **Type Jira** : `{FIELD_TYPES[ftype]}`")
            lines.append(f"- **Type fonctionnel** : {ftype}")
            lines.append("")
            lines.append("**Options à saisir :**")
            lines.append("")
            lines.append("- [ ] Oui")
            lines.append("- [ ] Non")
            lines.append("")
            lines.append("---")
            lines.append("")

    if count == 0:
        lines.append("_Aucun champ Radio/Checkbox dans ce lot._")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"📄 Guide des options exporté : {output_path} ({count} champs Radio/Checkbox)")


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
        type_key = field_def.get("type_key")  # optionnel : "text", "date", etc.
        # Si le type Jira est directement fourni, on l'utilise
        jira_type = field_def.get("type")
        searcher = field_def.get("searcherKey")

        # Si on a un type_key sémantique, on résout
        if type_key and type_key in FIELD_TYPES:
            jira_type = FIELD_TYPES[type_key]
            searcher = searcher or SEARCHER_TYPES[type_key]

        if not jira_type or not searcher:
            logger.warning(f"⚠️  Champ mal configuré (type/searcher manquant) : {name}")
            failed += 1
            continue

        existing_id = client.get_field_id_by_name(name)
        if existing_id:
            logger.info(f"⏭️  Champ déjà existant : {name} (id={existing_id}) — ignoré")
            skipped += 1
            continue

        result = client.create_custom_field(name, jira_type, searcher)
        if result:
            created += 1
        else:
            failed += 1

        time.sleep(0.5)

    export_options_guide(fields, OUTPUT_GUIDE)

    logger.info("=" * 60)
    logger.info(f"✅ Créés   : {created}")
    logger.info(f"⏭️  Ignorés : {skipped} (déjà existants)")
    logger.info(f"❌ Échecs   : {failed}")
    logger.info(f"📄 Guide des options : {OUTPUT_GUIDE}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()