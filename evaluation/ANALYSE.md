# Évaluation de l'OCR : analyse

Tableaux complets : [resultats.md](resultats.md), reproduits par `python -m evaluation run`.

## Conclusion

Avec le réglage du pipeline (image de 1540 px), **aucune erreur** n'a été mesurée : 1 455 valeurs exactes sur 1 455, dans 40 factures. Avec 40 factures sans erreur, on peut seulement affirmer, au seuil de 95 %, qu'au moins 91 % des factures de ce type sont lues sans faute.

| Image | Champs exacts (réel / synthétique) | Factures sans erreur | Temps par page (réel) |
|---|---|---|---|
| 650 px | 82,8 % / 88,2 % | 3 sur 40 | 5,0 s |
| 800 px | 99,0 % / 99,3 % | 31 sur 40 | 5,5 s |
| **1540 px** | **100 % / 100 %** | **40 sur 40** | **7,0 s** |
| 2339 px | 100 % / 100 % | 40 sur 40 | 9,1 s |

Le réglage 1540 px recommandé par la fiche du modèle est le bon compromis. À 2339 px, la lecture est 30 % plus lente sans gain mesurable. En dessous, le temps baisse peu et la qualité chute.

## Champs les plus fragiles

Le réglage actuel ne produisant aucune erreur, la fragilité se lit à 650 px (40 factures).

| Champ | Exact | Pourquoi |
|---|---|---|
| IBAN | 37,5 % | 27 caractères : une seule erreur suffit, et rien dans la phrase n'aide à deviner un chiffre |
| SIRET fournisseur | 52,5 % | 14 chiffres, confusions 0/6/8 |
| Ville fournisseur, ville client | 60 %, 62,5 % | Noms inventés et accents : le modèle les ramène vers un mot plausible (« ÉmilieVille » lu « Émile/Ville ») |
| Code postal client | 75 % | Chiffres isolés, sans redondance |
| Lignes de facture | 83 % | Voir ci-dessous |
| Dates, statut, catégorie, paiement, totaux | 97,5 à 100 % | Valeurs courtes, formats stables, vocabulaire courant |

- **Les lignes perdues viennent surtout de notre parseur.** Dans 7 factures, aucune ligne n'est extraite. Sur celle que nous avons examinée, le tableau est bien lu mais l'en-tête « Qté » est devenu « Qnk » : le parseur ne reconnaît plus le tableau et la facture est rejetée. Ces 7 cas expliquent 97 des 107 valeurs manquantes à 650 px.
- **Un écart reste inexpliqué** : le SIRET du client est exact à 97,5 %, celui du fournisseur à 52,5 %, alors que leur format est identique.

## Ce que rattrapent les contrôles qualité

À 650 et 800 px, 114 valeurs sont fausses. **105 (92 %)** se trouvent dans une facture signalée ou rejetée. Les 9 autres passent sans alerte : 7 villes ou codes postaux de clients et 2 désignations. Aucune erreur sur un montant, une date, un SIRET ou un IBAN n'est passée inaperçue.

Ce 92 % est mesuré par facture : une facture signalée pour une erreur peut en contenir une autre. Les erreurs non vues touchent les champs sans clé de contrôle ni redondance, surtout quand le client n'apparaît que sur peu de factures.

## Méthode

| Série | Vérité terrain | Intérêt et limite |
|---|---|---|
| 20 scans réels (2 ou 3 par fournisseur, tirés par empreinte du nom) | Transcription depuis les images | Représentative, mais faite par un assistant IA : **à relire par une personne** |
| 20 scans synthétiques, fabriqués à partir des PDF natifs | Couche texte des PDF, exacte | Sans saisie ni erreur de transcription, mais la dégradation est simulée |

Une vérité terrain fiable est donc obtenue sans des heures de saisie : les PDF natifs la fournissent. Le bruit, l'inclinaison et le fond des scans synthétiques sont réglés sur les 50 scans réels (corrélation du bruit : 0,67 contre 0,57). Les deux séries donnent des résultats voisins.

Une valeur n'est exacte que si elle est identique à la vérité, accents compris. Une valeur absente est comptée à part d'une valeur fausse, plus dangereuse.

## Limites

- **Transcription** : pour 3 des 20 scans réels (A-2025-0003, A-2025-0010, GPE-2026-0016), le résultat de l'OCR avait déjà été vu avant la transcription.
- **Échantillon** : 40 factures, mais 8 fournisseurs et une seule mise en page ; les valeurs d'un même fournisseur se répètent. Pour affirmer 99 % de factures sans erreur, il en faudrait environ 380 sans faute.
- **Parseur et contrôles** ont été mis au point sur ces mêmes 100 factures : d'autres fournisseurs donneraient sans doute moins bien.
- **Un seul passage par page** : avec une température de 0,2, les résultats à basse résolution peuvent varier d'un passage à l'autre.
- **Scans propres** : ni photo, ni tampon, ni pliure, ni écriture manuscrite.

## Pistes

1. Reconnaître le tableau même si un en-tête est mal lu.
2. Comparer les clients et fournisseurs à un référentiel, pour repérer une ville ou un code postal faux.
3. Tester des tailles entre 800 et 1540 px : sur un essai préalable de 2 scans, 1000 px ne donnait aucune erreur.
