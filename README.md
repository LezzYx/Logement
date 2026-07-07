# Crous Watcher — alertes Discord pour la phase complémentaire

Surveille automatiquement `trouverunlogement.lescrous.fr` toutes les 5 minutes
et envoie une alerte Discord dès qu'un **nouveau** logement correspondant à
tes filtres apparaît.

## 1. Récupérer ton URL de recherche filtrée

1. Va sur https://trouverunlogement.lescrous.fr/
2. Choisis la bonne campagne (année en cours / année prochaine).
3. Applique tes filtres : ville, prix maximum, surface, type de cohabitation, etc.
4. Copie l'URL complète dans la barre d'adresse une fois les filtres appliqués
   (elle contient tes critères sous forme de paramètres `?...`).
   → C'est ta `SEARCH_URL`.

## 2. Créer un webhook Discord

1. Dans ton serveur Discord : Paramètres du serveur → Intégrations → Webhooks
   → Nouveau webhook.
2. Choisis le salon où tu veux recevoir les alertes.
3. Copie l'URL du webhook.
   → C'est ta `DISCORD_WEBHOOK`.

## 3. Déployer sur GitHub Actions (gratuit, aucun serveur à gérer)

1. Crée un nouveau dépôt GitHub **public** (les secrets `SEARCH_URL` et
   `DISCORD_WEBHOOK` restent cachés même en public — seul le code générique
   est visible). C'est important : sur un dépôt **privé**, le plan gratuit
   GitHub Actions est limité à ~2000 min/mois, ce qui peut être dépassé par
   des exécutions toutes les 5 minutes en continu. Les dépôts publics ont des
   minutes Actions illimitées. Pousse-y ces trois fichiers en conservant
   l'arborescence :
   ```
   crous_watcher.py
   .github/workflows/watch.yml
   ```
2. Dans le dépôt : Settings → Secrets and variables → Actions → New repository secret
   - `SEARCH_URL` = l'URL copiée à l'étape 1
   - `DISCORD_WEBHOOK` = l'URL copiée à l'étape 2
3. Va dans l'onglet **Actions** du dépôt et active les workflows si demandé.
4. Le job tourne automatiquement toutes les 5 minutes. Tu peux aussi le lancer
   manuellement via "Run workflow" pour tester tout de suite.

Le premier lancement enregistre juste l'état actuel (aucune notif, pour éviter
de recevoir tous les logements déjà en ligne d'un coup). À partir du deuxième
lancement, seuls les **nouveaux** logements déclenchent une alerte Discord.

## 4. Tester en local (optionnel)

```bash
pip install requests beautifulsoup4
export SEARCH_URL="https://trouverunlogement.lescrous.fr/tools/45/search?..."
export DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
python crous_watcher.py
```

## 5. En cas de problème (site down, bug, changement de structure)

Le bot fait la différence entre "pas de nouveau logement" et "quelque chose ne
va pas" :

- Si une erreur survient (site inaccessible, erreur HTTP, page qui a changé
  de structure...), elle est comptée mais **ne déclenche pas d'alerte
  immédiatement** — le site peut être juste temporairement surchargé.
- Après **3 échecs consécutifs** (~15 minutes), tu reçois une alerte Discord
  dédiée (⚠️, en rouge), différente des alertes logement, avec le message
  d'erreur.
- Dès que ça refonctionne, un message "✅ retour à la normale" est envoyé.
- En parallèle, GitHub marque le run en échec (rouge) dans l'onglet Actions,
  et envoie normalement un email au propriétaire du dépôt en cas d'échec
  d'exécution planifiée — un filet de sécurité indépendant du bot.

Si tu reçois une alerte ⚠️, reviens vers Claude avec le message d'erreur
(visible aussi dans les logs de l'onglet Actions → le run en rouge → détail
de l'étape "Run watcher") pour qu'on corrige ensemble.


- Le site étant en accès public et rechargé "manuellement" par les étudiants
  eux-mêmes (le Crous recommande de "consulter régulièrement le site"), une
  fréquence de 5 minutes reste raisonnable. Évite de descendre sous 2-3 minutes.
- Si le site change de structure HTML, le sélecteur `a[href*="/accommodations/"]`
  dans `crous_watcher.py` est l'endroit à ajuster.
- `MAX_PAGES` (5 par défaut) limite le nombre de pages de résultats parcourues
  par cycle ; augmente-le si ta recherche filtrée a beaucoup de résultats.
