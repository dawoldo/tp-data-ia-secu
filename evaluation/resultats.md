# Résultats de l'évaluation OCR

Fichier généré par `python -m evaluation run`, ne pas modifier à la main.

## Vue d'ensemble

| Série | Image (px) | Factures | Factures sans erreur (IC 95 %) | Champs exacts | Manquants | Faux | dont non signalés | s/page |
|---|---|---|---|---|---|---|---|---|
| reel | 650 | 20 | 1 (1-24 %) | 588/710 (82,8 %) | 68 | 54 | 3 | 5,0 |
| reel | 800 | 20 | 16 (58-92 %) | 703/710 (99,0 %) | 1 | 6 | 0 | 5,5 |
| reel | 1540 | 20 | 20 (84-100 %) | 710/710 (100,0 %) | 0 | 0 | 0 | 7,0 |
| reel | 2339 | 20 | 20 (84-100 %) | 710/710 (100,0 %) | 0 | 0 | 0 | 9,1 |
| synth. | 650 | 20 | 2 (3-30 %) | 657/745 (88,2 %) | 39 | 49 | 2 | 5,2 |
| synth. | 800 | 20 | 15 (53-89 %) | 740/745 (99,3 %) | 0 | 5 | 4 | 5,2 |
| synth. | 1540 | 20 | 20 (84-100 %) | 745/745 (100,0 %) | 0 | 0 | 0 | 7,7 |
| synth. | 2339 | 20 | 20 (84-100 %) | 745/745 (100,0 %) | 0 | 0 | 0 | 9,3 |

« Faux » : une valeur a été lue mais elle est inexacte. « Non signalés » : valeurs fausses dans une facture que les contrôles qualité déclarent valide.

## État des factures après les contrôles qualité

| Série | Image (px) | Valides | Signalées | Rejetées | Illisibles |
|---|---|---|---|---|---|
| reel | 650 | 2 | 12 | 6 | 0 |
| reel | 800 | 15 | 4 | 1 | 0 |
| reel | 1540 | 20 | 0 | 0 | 0 |
| reel | 2339 | 20 | 0 | 0 | 0 |
| synth. | 650 | 2 | 12 | 6 | 0 |
| synth. | 800 | 18 | 2 | 0 | 0 |
| synth. | 1540 | 20 | 0 | 0 | 0 |
| synth. | 2339 | 20 | 0 | 0 | 0 |

## Précision champ par champ

Part de valeurs exactes. Entre parenthèses : manquantes + fausses.

| Champ | Valeurs | reel 650 | reel 800 | reel 1540 | reel 2339 | synth. 650 | synth. 800 | synth. 1540 | synth. 2339 |
|---|---|---|---|---|---|---|---|---|---|
| numero | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 95,0 % (0+1) | 100,0 % | 100,0 % | 100,0 % |
| date_emission | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| date_echeance | 20 | 95,0 % (1+0) | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| categorie | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| statut | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| mode_paiement | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| iban | 20 | 45,0 % (1+10) | 100,0 % | 100,0 % | 100,0 % | 30,0 % (1+13) | 100,0 % | 100,0 % | 100,0 % |
| total_ht | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| total_tva | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| total_ttc | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 95,0 % (1+0) | 100,0 % | 100,0 % | 100,0 % |
| detail_tva | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| fournisseur.nom | 20 | 90,0 % (0+2) | 100,0 % | 100,0 % | 100,0 % | 85,0 % (0+3) | 100,0 % | 100,0 % | 100,0 % |
| fournisseur.adresse | 20 | 80,0 % (0+4) | 100,0 % | 100,0 % | 100,0 % | 95,0 % (0+1) | 100,0 % | 100,0 % | 100,0 % |
| fournisseur.code_postal | 20 | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 95,0 % (0+1) | 100,0 % | 100,0 % | 100,0 % |
| fournisseur.ville | 20 | 60,0 % (0+8) | 90,0 % (0+2) | 100,0 % | 100,0 % | 60,0 % (0+8) | 100,0 % | 100,0 % | 100,0 % |
| fournisseur.siret | 20 | 45,0 % (1+10) | 95,0 % (1+0) | 100,0 % | 100,0 % | 60,0 % (2+6) | 100,0 % | 100,0 % | 100,0 % |
| fournisseur.tva_intracom | 20 | 95,0 % (1+0) | 95,0 % (0+1) | 100,0 % | 100,0 % | 90,0 % (2+0) | 100,0 % | 100,0 % | 100,0 % |
| client.nom | 20 | 95,0 % (0+1) | 100,0 % | 100,0 % | 100,0 % | 95,0 % (0+1) | 100,0 % | 100,0 % | 100,0 % |
| client.adresse | 20 | 95,0 % (0+1) | 100,0 % | 100,0 % | 100,0 % | 80,0 % (0+4) | 100,0 % | 100,0 % | 100,0 % |
| client.code_postal | 20 | 70,0 % (0+6) | 90,0 % (0+2) | 100,0 % | 100,0 % | 80,0 % (0+4) | 100,0 % | 100,0 % | 100,0 % |
| client.ville | 20 | 55,0 % (0+9) | 95,0 % (0+1) | 100,0 % | 100,0 % | 70,0 % (0+6) | 80,0 % (0+4) | 100,0 % | 100,0 % |
| client.siret | 20 | 95,0 % (0+1) | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| nombre de lignes | 20 | 80,0 % (4+0) | 100,0 % | 100,0 % | 100,0 % | 85,0 % (3+0) | 100,0 % | 100,0 % | 100,0 % |
| ligne.designation | 50 / 57 | 72,0 % (12+2) | 100,0 % | 100,0 % | 100,0 % | 87,7 % (6+1) | 98,2 % (0+1) | 100,0 % | 100,0 % |
| ligne.quantite | 50 / 57 | 76,0 % (12+0) | 100,0 % | 100,0 % | 100,0 % | 89,5 % (6+0) | 100,0 % | 100,0 % | 100,0 % |
| ligne.prix_unitaire_ht | 50 / 57 | 76,0 % (12+0) | 100,0 % | 100,0 % | 100,0 % | 89,5 % (6+0) | 100,0 % | 100,0 % | 100,0 % |
| ligne.taux_tva | 50 / 57 | 76,0 % (12+0) | 100,0 % | 100,0 % | 100,0 % | 89,5 % (6+0) | 100,0 % | 100,0 % | 100,0 % |
| ligne.total_ht | 50 / 57 | 76,0 % (12+0) | 100,0 % | 100,0 % | 100,0 % | 89,5 % (6+0) | 100,0 % | 100,0 % | 100,0 % |

## Erreurs

### reel, 650 px

| Facture | Champ | Attendu | Lu | État |
|---|---|---|---|---|
| facture_A-2025-0003_scan.pdf | fournisseur.siret | 77360260298050 | 77360280298050 | signalee |
| facture_A-2025-0010_scan.pdf | date_echeance | 2025-06-16 | (rien) | rejetee |
| facture_A-2025-0010_scan.pdf | iban | FR1578820812191361939909169 | FR1578825812191361939909169 | rejetee |
| facture_A-2025-0010_scan.pdf | client.code_postal | 48529 | 48539 | rejetee |
| facture_BS-2026-0001_scan.pdf | iban | FR4545053315869232260256342 | FR4545053315869232280256342 | signalee |
| facture_BS-2026-0001_scan.pdf | fournisseur.ville | Saint ÉmilieVille | Saint Émile/Ville | signalee |
| facture_BS-2026-0001_scan.pdf | fournisseur.siret | 48740164859826 | 48740164859636 | signalee |
| facture_BS-2026-0001_scan.pdf | client.ville | Sainte Matthieu-les-Bains | Sainte Mathieu-les-Bains | signalee |
| facture_BS-2026-0007_scan.pdf | iban | FR4545053315869232260256342 | FR4540553315689232280256342 | signalee |
| facture_BS-2026-0007_scan.pdf | fournisseur.adresse | 82, avenue de Guilbert | 82, avenue de Guibert | signalee |
| facture_BS-2026-0007_scan.pdf | fournisseur.ville | Saint ÉmilieVille | Saint Émile/Ville | signalee |
| facture_BS-2026-0007_scan.pdf | client.ville | Sainte Monique | Sarais Monique | signalee |
| facture_C-2026-0004_scan.pdf | client.code_postal | 20175 | 28175 | valide |
| facture_C-2026-0004_scan.pdf | ligne.designation | Contrat de maintenance mensuel | Control de maintenance mensuel | valide |
| facture_C-2026-0007_scan.pdf | client.ville | Sainte Dominiquenec | Sainte Dominique nec | valide |
| facture_C-2026-0014_scan.pdf | iban | FR5476483503056413953767242 | FR5476483603056413953767242 | signalee |
| facture_C-2026-0014_scan.pdf | fournisseur.siret | 49593103241928 | 48593103241928 | signalee |
| facture_GPE-2025-0003_scan.pdf | iban | FR4513338726247317810801326 | (rien) | signalee |
| facture_GPE-2026-0016_scan.pdf | iban | FR4513338726247317810801326 | FR4513338728247317810801326 | signalee |
| facture_GPE-2026-0016_scan.pdf | fournisseur.nom | Gimenez Payet et Fils | Ginennes Payet et Fils | signalee |
| facture_GPE-2026-0016_scan.pdf | fournisseur.adresse | 873, rue Étienne Pereira | 933, rue Étienne Pereira | signalee |
| facture_GPE-2026-0016_scan.pdf | client.code_postal | 17905 | 17505 | signalee |
| facture_GPE-2026-0016_scan.pdf | client.ville | Poulain-la-Forêt | Poulan-la-Fonte | signalee |
| facture_LG-2025-0005_scan.pdf | iban | FR2383465787133150983930103 | FR22834657871931509830030103 | signalee |
| facture_LG-2025-0005_scan.pdf | fournisseur.nom | Le Gall | Le Gali | signalee |
| facture_LG-2025-0005_scan.pdf | fournisseur.ville | Saint Gilbertdan | Saint Gilbertsan | signalee |
| facture_LG-2025-0005_scan.pdf | client.ville | Sainte Matthieu-les-Bains | Sainte Mattheu-les-Bains | signalee |
| facture_LG-2025-0005_scan.pdf | ligne.designation | Disque SSD externe 2 To | Droque SSD externe 2 To | signalee |
| facture_LG-2026-0004_scan.pdf | iban | FR2383465787133150983930103 | FR236534657871331509933930103 | rejetee |
| facture_LG-2026-0004_scan.pdf | fournisseur.ville | Saint Gilbertdan | Saint Gilbertsan | rejetee |
| facture_LG-2026-0004_scan.pdf | fournisseur.siret | 88095701482489 | 88095701462486 | rejetee |
| facture_LG-2026-0004_scan.pdf | client.siret | 13518233508240 | 13518233506240 | rejetee |
| facture_LG-2026-0004_scan.pdf | nombre de lignes | 3 | (rien) | rejetee |
| facture_LG-2026-0004_scan.pdf | ligne.designation | Disque SSD externe 2 To | (rien) | rejetee |
| facture_LG-2026-0004_scan.pdf | ligne.quantite | 12 | (rien) | rejetee |
| facture_LG-2026-0004_scan.pdf | ligne.prix_unitaire_ht | 111.36 | (rien) | rejetee |
| facture_LG-2026-0004_scan.pdf | ligne.taux_tva | 20 | (rien) | rejetee |
| facture_LG-2026-0004_scan.pdf | ligne.total_ht | 1336.32 | (rien) | rejetee |
| facture_LG-2026-0004_scan.pdf | ligne.designation | Station d'accueil USB-C | (rien) | rejetee |
| facture_LG-2026-0004_scan.pdf | ligne.quantite | 4 | (rien) | rejetee |
| ... | 82 autres | | | |

### reel, 800 px

| Facture | Champ | Attendu | Lu | État |
|---|---|---|---|---|
| facture_P-2025-0002_scan.pdf | fournisseur.ville | Saint Élise-sur-Mer | Saint Elise-sur-Mer | signalee |
| facture_P-2025-0002_scan.pdf | fournisseur.tva_intracom | FR35985435346 | FR36985435346 | signalee |
| facture_P-2025-0002_scan.pdf | client.ville | Sainte Dominiquenec | Sainte Dominiqueynec | signalee |
| facture_P-2025-0008_scan.pdf | fournisseur.ville | Saint Élise-sur-Mer | Saint Elise-sur-Mer | signalee |
| facture_P-2025-0008_scan.pdf | client.code_postal | 59525 | 59625 | signalee |
| facture_V-2025-0003_scan.pdf | client.code_postal | 88105 | 88106 | signalee |
| facture_V-2025-0009_scan.pdf | fournisseur.siret | 38849696066978 | (rien) | rejetee |

### synth., 650 px

| Facture | Champ | Attendu | Lu | État |
|---|---|---|---|---|
| facture_A-2025-0005_synth.pdf | iban | FR1578820812191361939909169 | FR1578820812191361929909169 | rejetee |
| facture_A-2025-0005_synth.pdf | fournisseur.nom | Aubry | Autry | rejetee |
| facture_A-2025-0005_synth.pdf | client.ville | Barre-la-Forêt | Bane-la-Fovêt | rejetee |
| facture_A-2025-0005_synth.pdf | nombre de lignes | 3 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.designation | Atelier de cadrage projet | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.quantite | 9 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.prix_unitaire_ht | 1363.93 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.taux_tva | 20 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.total_ht | 12275.37 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.designation | Journée de conseil data engineering | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.quantite | 7 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.prix_unitaire_ht | 829.40 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.taux_tva | 20 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.total_ht | 5805.80 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.designation | Formation DuckDB et Parquet | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.quantite | 12 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.prix_unitaire_ht | 1673.05 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.taux_tva | 20 | (rien) | rejetee |
| facture_A-2025-0005_synth.pdf | ligne.total_ht | 20076.60 | (rien) | rejetee |
| facture_A-2026-0006_synth.pdf | client.code_postal | 76924 | 76024 | valide |
| facture_A-2026-0006_synth.pdf | client.ville | Saint Adélaïdenec | Saint Adéolédenec | valide |
| facture_A-2026-0008_synth.pdf | iban | FR1578820812191361939909169 | (rien) | signalee |
| facture_BS-2025-0003_synth.pdf | iban | FR4545053315869232260256342 | FR45450533158689232260256242 | signalee |
| facture_BS-2025-0003_synth.pdf | fournisseur.ville | Saint ÉmilieVille | Saint ÉmileVille | signalee |
| facture_BS-2025-0003_synth.pdf | fournisseur.siret | 48740164859826 | 48740164809636 | signalee |
| facture_BS-2025-0003_synth.pdf | fournisseur.tva_intracom | FR20487401648 | (rien) | signalee |
| facture_BS-2026-0004_synth.pdf | iban | FR4545053315869232260256342 | FR49450053315869232260256342 | rejetee |
| facture_BS-2026-0004_synth.pdf | total_ttc | 521.14 | (rien) | rejetee |
| facture_BS-2026-0004_synth.pdf | fournisseur.ville | Saint ÉmilieVille | Saint ÉmileVille | rejetee |
| facture_BS-2026-0004_synth.pdf | fournisseur.siret | 48740164859826 | 48740164859626 | rejetee |
| facture_BS-2026-0004_synth.pdf | client.nom | Torres | Tones | rejetee |
| facture_BS-2026-0006_synth.pdf | iban | FR4545053315869232260256342 | FR4545053315869232280256342 | rejetee |
| facture_BS-2026-0006_synth.pdf | fournisseur.ville | Saint ÉmilieVille | Saint Émile/Ville | rejetee |
| facture_BS-2026-0006_synth.pdf | fournisseur.siret | 48740164859826 | 48740164809626 | rejetee |
| facture_BS-2026-0006_synth.pdf | client.adresse | 4, chemin Roger Muller | 4, chernin Roger Muller | rejetee |
| facture_BS-2026-0006_synth.pdf | nombre de lignes | 2 | (rien) | rejetee |
| facture_BS-2026-0006_synth.pdf | ligne.designation | Ramette papier A4 500 feuilles | (rien) | rejetee |
| facture_BS-2026-0006_synth.pdf | ligne.quantite | 8 | (rien) | rejetee |
| facture_BS-2026-0006_synth.pdf | ligne.prix_unitaire_ht | 6.73 | (rien) | rejetee |
| facture_BS-2026-0006_synth.pdf | ligne.taux_tva | 20 | (rien) | rejetee |
| ... | 48 autres | | | |

### synth., 800 px

| Facture | Champ | Attendu | Lu | État |
|---|---|---|---|---|
| facture_A-2025-0005_synth.pdf | client.ville | Barre-la-Forêt | Barre-la-Foixét | valide |
| facture_A-2026-0006_synth.pdf | client.ville | Saint Adélaïdenec | Saint Adélaidenec | valide |
| facture_C-2025-0015_synth.pdf | client.ville | Sainte Dominiquenec | Sainte Dominique nec | signalee |
| facture_P-2025-0005_synth.pdf | client.ville | Labbé-les-Bains | Labbé-les Bains | valide |
| facture_V-2025-0011_synth.pdf | ligne.designation | Lot de stylos bille bleus | Lot de stylos bille bleue | valide |
