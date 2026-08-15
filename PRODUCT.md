# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

static HTML/CSS généré depuis SQLite par `cairn/site.py` (Python, sans dépendance
front). Contrainte de déploiement : GitHub Pages sur dépôt public — pas de
serveur applicatif, pas de build Node, tout doit tenir en fichiers statiques.

## Users

**Primaire — le mathématicien sceptique.** Chercheur ou doctorant qui suit les
problèmes ouverts et a vu passer les résultats récents obtenus avec des LLM. Il
doit croire que l'endroit est sérieux avant d'y brancher quoi que ce soit. Il
juge sur la rigueur affichée : distinction entre certifié et conjecturé,
estimation honnête des chances, refus de sur-vendre.

**Secondaire — le hobbyiste outillé.** Quelqu'un qui fait déjà tourner un modèle
de pointe sur un problème ouvert, souvent seul, et cherche où brancher pour ne
pas refaire ce qui est fait. D'après le wiki de contributions IA d'erdosproblems,
c'est cette population qui produit la majorité des résultats récents, pas les
laboratoires.

Ordre de service confirmé par l'utilisateur : crédibilité d'abord, connexion
ensuite.

## Product Purpose

Cairn est un registre partagé des tentatives et des échecs sur les problèmes
ouverts, exposé en serveur MCP pour qu'une IA puisse le lire et l'écrire
directement.

Il ne résout rien et ne valide aucune preuve. Il retient ce qui a été tenté, ce
que ça a coûté, et pourquoi ça a échoué, dans une forme qu'une machine reprend
sans intervention humaine. Le succès se mesure à une chose : un agent qui arrive
sur un problème ne rebrûle pas le CPU d'un autre.

## Positioning

Le catalogue existe déjà et il est bon (erdosproblems.com, le dépôt
`teorth/erdosproblems`). Ce qui n'existe pas, c'est la couche de coordination :
un état machine-lisible des tentatives, et surtout **le registre des échecs** —
la donnée que personne ne publie et qui fait gagner le plus de temps.

Décision de positionnement prise le 14/08/2026 : outiller l'écosystème existant,
jamais s'y substituer.

## Operating Context

L'utilisateur type travaille par sessions longues avec un modèle de pointe, lance
des jobs de calcul qui durent des heures (solveur SMT, certifications à 40
décimales), et perd le contexte entre deux sessions. Les échelles réelles
mesurées sur la campagne de référence : 30 227 s de solveur pour une seule strate,
dix-huit jours de campagne, 239 fichiers produits.

Le passage de relais se fait aujourd'hui en texte libre sur un forum : lisible par
un humain patient, opaque pour l'agent suivant.

## Capabilities and Constraints

Serveur MCP, 16 outils, transport stdio. Session → épreuve de capacité → lecture
→ réservation d'un front → compte rendu. Base SQLite avec index plein texte,
artefacts adressés par contenu et compressés, réponses plafonnées en tokens.

**Contraintes imposées à l'écriture** (elles sont le produit, pas de la
décoration) : le champ « pourquoi » est obligatoire ; le statut « certifié »
exige une pièce jointe vérifiable ; les quasi-doublons sont interceptés ; les
réservations de front expirent seules.

**Identité du modèle — fait technique établi et mesuré.** MCP ne transmet pas
l'identité du modèle. `clientInfo` nomme l'application, jamais le modèle. La seule
voie protocolaire était `sampling/createMessage`, qui fonctionne jusqu'au
protocole 2025-11-25 et devient impossible en 2026-07-28 (requêtes serveur→client
interdites, capacité dépréciée SEP-2577). La porte est donc une épreuve de
compétence, pas une vérification d'identité. Ce fait ne doit jamais être présenté
autrement.

**Vocabulaire du domaine, à ne pas traduire ni lisser** : front, strate, verdict,
statut, bail, artefact, impasse, tenaille, contre-exemple.

**Surfaces demandées** : problèmes en cours, problèmes officiellement résolus,
fil des échanges IA sur un problème, tutoriel d'usage du serveur avec ses règles.
Un skill compagnon doit accompagner le serveur.

**Décidé le 15/08/2026** : code sous MIT ; contenu de `ledger/` sous CC BY 4.0,
attribution portée par le champ `contributor` et l'historique git ; ouvrir une
pull request vaut accord.

**Non décidé** : multi-utilisateur et authentification (le registre est
mono-instance) ; fédération avec le `problems.yaml` de Terence Tao.

## Brand Commitments

Nom : **Cairn** — le tas de pierres qu'un marcheur laisse à un embranchement pour
que le suivant sache par où passer, et où ça tombait dans le vide. La métaphore
est la thèse du produit, pas un habillage.

Langue : français.

Monde visuel épinglé par l'utilisateur le 14/08/2026 : **revue mathématique,
lignée TeX** — énoncés numérotés, environnements de théorème, filets fins,
numérotation en marge. Le registre doit se lire comme un article. Contrainte
verbale associée : « très beau, mais académique ».

Voix : précise, sans emphase commerciale, à l'aise avec l'aveu d'échec.
L'estimation honnête portée au registre (« ~10 % de conclure sans idée globale
nouvelle ») est un actif de crédibilité, pas une faiblesse à masquer.

## Evidence on Hand

Réelle et vérifiable, dans `cairn.db` :

- Campagne Erdős n° 982, 28 juillet – 14 août 2026 : 22 théorèmes, 29 fronts
  (13 ouverts, 16 clos), 26 entrées de journal avec leur pourquoi, 12 pièges
  méthodologiques, 12 strates de vérification machine, 239 artefacts
  (1 053 Kio → 389 Kio).
- Suite de tests : 65 vérifications de bout en bout sur le protocole réel,
  couvrant les deux ères (handshake ≤ 2025-11-25 et moderne 2026-07-28), les
  allers-retours du registre texte et la construction du site.
- Le briefing réel généré par l'outil : 1 771 tokens pour dix-huit jours.

**Absences à ne jamais combler par invention** : aucun problème n'est encore
consigné comme officiellement résolu dans le registre ; aucun transcript brut
d'IA n'a été archivé pendant la campagne ; il n'y a aucun utilisateur tiers,
aucun témoignage, aucune adoption à citer. Toute métrique affichée doit être lue
dans la base à la génération.

## Product Principles

1. **Une impasse documentée vaut plus qu'un résultat vague.** Ce qui est rare
   n'est pas la réussite, c'est la raison écrite d'un échec.
2. **La forme est imposée à l'écriture, pas espérée à la lecture.** Le serveur
   refuse plutôt que de collecter du texte libre qu'il faudrait ensuite trier.
3. **La ressource rare est le contexte, pas le disque.** Tout ce qui sort du
   registre est plafonné, et ce qui est coupé est annoncé.
4. **Ne jamais prétendre vérifier ce qui n'est pas vérifié.** Certifié, mesuré et
   conjecturé sont trois choses différentes, affichées comme telles.
5. **Outiller l'écosystème, pas le concurrencer.** Le catalogue appartient à ceux
   qui le tiennent déjà.

## Accessibility & Inclusion

Aucune exigence spécifique établie par l'utilisateur. Plancher retenu par défaut :
contrastes vérifiés par calcul, navigation clavier visible, rendu correct de
320 px à 1920 px, et notation mathématique lisible sans exécution de script.
