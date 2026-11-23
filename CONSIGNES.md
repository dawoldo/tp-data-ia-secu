# Projet : de la facture scannée à l'agent IA

## Contexte

Une entreprise reçoit chaque mois des dizaines de factures fournisseurs au format PDF. Certaines
sont des PDF « natifs » avec du texte sélectionnable, d'autres sont **scannées** : de simples images,
sans aucun texte. Aujourd'hui, une personne les ressaisit à la main dans un tableur. La direction veut :

1. extraire automatiquement les informations de chaque facture ;
2. les stocker proprement dans une plateforme de données analytique ;
3. pouvoir poser des questions en langage naturel (« Quel est le montant TTC des factures en retard
   en 2025 ? ») à un assistant IA qui interroge ces données.

Votre mission : construire cette chaîne de bout en bout, de façon reproductible.

```
 PDF (bucket S3) ──► extraction / OCR ──► bronze ──► silver ──► entrepôt ──► serveur MCP ──► agent IA
```

## Objectifs pédagogiques

À la fin du projet, vous saurez :

- concevoir une **architecture médaillon** (bronze / silver) et justifier le rôle de chaque couche ;
- intégrer un **modèle d'OCR** exposé derrière une API et mesurer objectivement sa qualité ;
- mettre en place des **contrôles de qualité** de données et une zone de quarantaine ;
- séparer **stockage** et **calcul** ;
- exposer des données à une IA via le **Model Context Protocol (MCP)** ;
- construire un **agent** capable d'utiliser des outils, indépendamment du fournisseur de LLM ;
- réfléchir à l'**industrialisation** d'une telle chaîne.

## Choix techniques

**Vous êtes libres** de choisir les technologies, langages, bibliothèques et outils que vous voulez,
pour chaque brique : stockage, moteur de requêtes, serveur MCP, framework d'agent, LLM, etc.

Les seules exigences portent sur ce que fait votre système :

- l'OCR passe par le modèle **LightOnOCR-3** mis à votre disposition (voir ci-dessous) ;
- les données sont organisées en couches **bronze** et **silver** ;
- l'accès des IA aux données passe par un **serveur MCP** ;
- le LLM de l'agent doit être **interchangeable par simple configuration**.

Chaque choix technique doit être **justifié** dans votre rapport.

## Ressources fournies

### Les factures

Un jeu de **100 factures** est disponible dans le bucket S3 `s3://factures`, sur le point d'accès
`https://dams-5.s3-gateway.console.hyperfluid.cloud`. Les identifiants d'accès vous seront communiqués
par votre enseignant : ne les écrivez jamais en clair dans votre dépôt.

Le jeu mélange des PDF avec couche texte et des PDF scannés (images uniquement), dans des proportions
proches de la réalité.

### Le modèle d'OCR

Le modèle **LightOnOCR-3** est déployé sur Hyperfluid :
<https://dams-5.console.hyperfluid.cloud/harbors/default/sapience/shared-models/lightonocr-3-1b-test/overview>

Pour l'utiliser, **créez une clé d'API** depuis la console Hyperfluid. La page du modèle indique
l'adresse du point d'accès et la façon de l'appeler. Documentation du modèle :
<https://huggingface.co/lightonai/LightOnOCR-3-1B>

---

## Étape 1 : récupérer les factures

**À faire**

- Téléchargez les factures depuis le bucket S3 vers une zone d'arrivée.
- Pour chaque PDF, déterminez s'il contient une couche texte exploitable ou s'il s'agit d'une image
  qui nécessite de l'OCR.

**Critères de validation**

- Une commande récupère les nouvelles factures du bucket.
- Vous savez dire, pour chaque fichier, s'il est « texte » ou « image ».

## Étape 2 : appeler le modèle d'OCR

**À faire**

- Créez votre clé d'API sur Hyperfluid et envoyez une page de facture au modèle.
- Récupérez le texte reconnu et étudiez son format.
- Mesurez le **temps de traitement par page**.

**Critères de validation**

- Une commande envoie une page au modèle et affiche le résultat.
- Vous connaissez le format de sortie du modèle (structure du texte, rendu des tableaux).

**Questions à vous poser**

- Lisez **attentivement** la fiche du modèle (*model card*) : quel format de requête attend-il ?
  Quelle résolution d'image ? Que se passe-t-il si vous ne respectez pas ces recommandations ?
- Quel compromis entre la taille de l'image, la vitesse et la qualité de lecture ?
- Votre code doit-il dépendre de ce fournisseur d'OCR ? Comment en changer sans tout réécrire ?
- Où stocker la clé d'API pour qu'elle ne se retrouve jamais dans votre dépôt Git ?

## Étape 3 : couche bronze

La couche bronze conserve les données **brutes**, telles qu'extraites, avec leur traçabilité.

**À faire**

- Pour chaque PDF, stockez le texte extrait et les métadonnées utiles.
- Les PDF qui ont une couche texte n'ont pas besoin d'OCR ; les autres, si.
- Le traitement doit être **incrémental** : relancer le pipeline ne doit pas retraiter (ni ré-OCRiser)
  un fichier déjà ingéré.

**Critères de validation**

- Lancer le pipeline deux fois de suite : la seconde exécution n'ajoute rien et ne fait aucun appel
  OCR.
- Si le service d'OCR est indisponible, le pipeline ne plante pas : l'erreur est tracée et le fichier
  sera retraité plus tard.

**Questions à vous poser**

- Comment reconnaître qu'un fichier a « déjà été vu » ? Le nom du fichier suffit-il ?
- Quelles métadonnées garder pour pouvoir, plus tard, expliquer d'où vient une valeur ?
- Pourquoi ne faut-il **jamais** modifier ou supprimer les données de la couche bronze ?

## Étape 4 : couche silver

La couche silver contient des données **propres, typées et contrôlées**.

**À faire**

- Transformez le texte brut en tables structurées : au minimum une table des factures (une ligne par
  facture) et une table des lignes de facture.
- Typez correctement les colonnes (dates, montants…).
- Mettez en place des **contrôles de qualité** et une table de **quarantaine** (rejets) qui explique
  pourquoi un document a été écarté.

**Critères de validation**

- Aucune facture valide n'est perdue, aucun doublon ne passe.
- Chaque facture porte un statut de qualité ; chaque rejet porte un motif.
- Les factures dont les montants sont incohérents sont détectées.

**Questions à vous poser**

- Quel type de donnée utiliser pour des montants en euros ? Pourquoi pas un nombre flottant ?
- Le texte produit par l'OCR n'a pas la même forme que celui d'un PDF natif : comment écrire un
  parseur robuste à ces variations ?
- Si l'OCR lit mal un montant, faut-il le « corriger » automatiquement ? Quelles conséquences ?
- Quelle différence entre une facture *rejetée* et une facture *signalée* ?

## Étape 5 : mesurer la qualité de l'OCR

**À faire**

- Constituez une **vérité terrain** : les valeurs exactes d'un échantillon de factures scannées.
- Écrivez un programme qui compare votre couche silver à cette vérité terrain et calcule la
  **précision champ par champ**.
- Testez au moins deux réglages (par exemple deux résolutions d'image) et comparez.

**Critères de validation**

- Un tableau de résultats par champ, reproductible avec une commande.
- Une courte analyse : quels champs sont les plus fragiles, et pourquoi ?

**Questions à vous poser**

- Comment obtenir une vérité terrain fiable sans y passer des heures ?
- Quelle taille d'échantillon faut-il pour que la mesure ait un sens ?

## Étape 6 : l'entrepôt de données

**À faire**

- Rendez les couches bronze et silver interrogeables en SQL.
- Séparez **stockage** et **calcul** : les données ne doivent exister qu'en un seul exemplaire.
- L'entrepôt doit pouvoir être consulté depuis un outil graphique (DBeaver par exemple) et depuis
  vos programmes.

**Critères de validation**

- Une requête SQL sur la couche silver fonctionne depuis votre machine et depuis vos programmes.
- Consulter l'entrepôt depuis un outil graphique n'empêche pas le reste du système de fonctionner.

**Questions à vous poser**

- Que se passe-t-il si plusieurs programmes accèdent aux mêmes données en même temps ?
- Si votre entrepôt fait référence à des fichiers, comment ces références restent-elles valides sur
  votre machine, dans un conteneur et chez un collègue ?

## Étape 7 : le serveur MCP

Le [Model Context Protocol](https://modelcontextprotocol.io/) permet à une IA d'utiliser des outils
que vous exposez.

**À faire**

- Écrivez un serveur MCP qui donne accès à l'entrepôt. Il doit au minimum permettre de :
  - lister des factures avec des filtres (fournisseur, client, statut, période…) ;
  - obtenir le nombre et les totaux de factures avec ces mêmes filtres ;
  - obtenir le détail d'une facture et de ses lignes ;
  - découvrir le schéma des données ;
  - exécuter une requête SQL libre **en lecture seule**.
- Chaque réponse d'outil doit indiquer la ou les **requêtes SQL réellement exécutées**, pour la
  transparence.
- Branchez-le sur un client MCP existant (Claude Desktop, Claude Code…) et montrez une conversation
  qui l'utilise.

**Critères de validation**

- Un script de test appelle chaque outil et vérifie les résultats.
- Il est impossible de modifier ou supprimer des données via le serveur, même avec l'outil SQL libre.

**Questions à vous poser**

- Le LLM choisit ses outils d'après leur **nom** et leur **description** : comment les rédiger pour
  qu'il fasse le bon choix ?
- Un argument d'outil vient d'un LLM, donc d'une source non fiable : comment éviter les injections SQL ?
- Que doit renvoyer un outil en cas d'erreur pour que le LLM puisse se corriger ?

## Étape 8 : l'agent

**À faire**

- Écrivez un agent qui répond en français aux questions sur les factures en utilisant **uniquement**
  les outils de votre serveur MCP.
- Le LLM doit être **interchangeable par configuration** : par exemple un modèle local et un modèle
  hébergé.
- L'utilisateur doit **voir** ce que fait l'agent : outils appelés, requêtes SQL, résultats.
- L'agent garde le fil de la conversation et s'arrête proprement.

**Critères de validation**

- Une même question posée avec deux LLM différents, sans changer le code.
- Les chiffres annoncés par l'agent sont exacts : vérifiez-les par une requête SQL.

**Questions à vous poser**

- Comment empêcher l'agent d'inventer des chiffres ?
- Un petit modèle local et un grand modèle hébergé se comportent-ils de la même façon ? Notez vos
  observations (vitesse, choix des outils, exactitude).

## Étape 9 : industrialisation (question ouverte)

Votre système fonctionne sur votre machine. Comment le faire tourner **en production**, pour des
milliers de factures par mois, avec plusieurs utilisateurs ?

**À faire**

Proposez une démarche d'industrialisation argumentée. Vous pouvez par exemple aborder :
le déploiement, l'automatisation des traitements, la montée en charge de l'OCR, la sécurité des accès
et des secrets, la supervision, la gestion des erreurs, les tests, les coûts…

Ce n'est pas une liste à cocher : choisissez les sujets qui vous semblent les plus importants,
justifiez vos priorités et, si vous le pouvez, implémentez une partie de votre proposition.

---

## Livrables

1. Le **dépôt Git** du projet, avec un historique de commits lisible.
2. Des **instructions claires pour lancer le projet** : un nouvel arrivant doit pouvoir tout faire
   tourner facilement, en quelques commandes, en suivant uniquement votre documentation.
3. Un **rapport** de 4 à 6 pages :
   - schéma d'architecture et justification de vos choix techniques ;
   - résultats de l'évaluation OCR (étape 5) et leur analyse ;
   - votre proposition d'industrialisation (étape 9) ;
   - difficultés rencontrées, limites actuelles et pistes d'amélioration.
4. Une **démonstration** de 10 minutes : de la récupération des factures jusqu'à une conversation
   avec l'agent.

## Barème indicatif (sur 20)

| Critère | Points |
|---|---|
| Récupération des factures et détection texte / image | 1 |
| Intégration de l'OCR | 2 |
| Couche bronze (traçabilité, incrémental, gestion des erreurs) | 2 |
| Couche silver (typage, contrôles qualité, quarantaine) | 3 |
| Évaluation de l'OCR et analyse | 2 |
| Entrepôt (séparation stockage / calcul) | 1 |
| Serveur MCP (outils, sécurité, transparence SQL, tests) | 3 |
| Agent (LLM interchangeable, affichage, robustesse) | 2 |
| Facilité de lancement et documentation | 1 |
| Proposition d'industrialisation | 2 |
| Rapport et démonstration | 1 |

## Bonus

- Une couche **gold** : indicateurs métier (chiffre d'affaires mensuel, encours par fournisseur…)
  et outils MCP associés.
- Un **générateur** de fausses factures pour enrichir votre jeu de test (scans réalistes, anomalies
  volontaires, vérité terrain produite automatiquement).
- Comparer LightOnOCR-3 à un autre moteur d'OCR sur votre jeu d'évaluation.
- Tests automatisés lancés en intégration continue.

## Conseils

- Avancez **étape par étape** et validez chaque étape avant de passer à la suivante.
- Commencez petit (5 à 10 factures), puis passez à l'ensemble du jeu.
- Lisez la documentation officielle de chaque outil **avant** de coder.
- Gardez une trace de vos mesures et de vos essais : elle nourrira votre rapport.

## Ressources

- Modèle LightOnOCR-3 sur Hyperfluid :
  <https://dams-5.console.hyperfluid.cloud/harbors/default/sapience/shared-models/lightonocr-3-1b-test/overview>
- Fiche du modèle LightOnOCR-3 : <https://huggingface.co/lightonai/LightOnOCR-3-1B>
- Model Context Protocol : <https://modelcontextprotocol.io/>
