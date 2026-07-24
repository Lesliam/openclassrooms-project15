# Conception d'une voie de mise à jour OTA par BLE — terminal Coach Vocal FR

Document de conception. La mise à jour à distance par BLE a été **réduite à une
conception documentée** en semaine 1 par l'échelle de réduction de périmètre du
sprint (voir `planning.md` et le §4.1 du rapport de conduite de projet) :
l'implémentation n'est pas réalisée dans cette itération, le flash reste manuel
et la mise à jour Wi-Fi existante suffit au MVP. Ce document fige la conception
pour qu'elle puisse être reprise sans re-décision.

Sauf mention contraire, les faits matériels et de configuration cités
proviennent de la configuration effectivement construite pour le terminal
(`firmware/esphome/coach-terminal-base.yaml`, `partitions.csv` et le
`sdkconfig` du build `coach-terminal`, relus le 2026-07-24).

## 1. Objectif et périmètre

Le terminal dispose déjà d'une mise à jour OTA par Wi-Fi : composant `ota`
d'ESPHome, plateforme `esphome`, protégée par mot de passe
(`coach-terminal-base.yaml`, section `ota`). Cette voie est suffisante en
usage nominal — l'appareil est sur le réseau local du foyer et flashé depuis le
poste de développement.

Une voie BLE complémentaire répond à trois situations que la voie Wi-Fi ne
couvre pas :

- **Approvisionnement initial** (« provisioning ») : poser à jour un terminal
  sorti de carton **sans** lui saisir au préalable des identifiants Wi-Fi.
- **Récupération** : reprendre la main quand la configuration Wi-Fi est
  erronée. Le fichier de configuration note déjà qu'une passerelle IP statique
  mal renseignée rend l'appareil injoignable et **impose un reflash série** ;
  BLE offrirait un chemin de secours sans démontage.
- **Mise à jour hors infrastructure** : intervenir sur un terminal déplacé hors
  du réseau connu, à portée radio directe d'un téléphone d'exploitation.

BLE ne remplace pas la voie Wi-Fi (débit bien moindre, portée courte) : c'est un
chemin de secours et d'amorçage, à réserver aux cas ci-dessus.

## 2. Contraintes matérielles

**Carte.** ESP32-S3-WROOM-1 (variante `esp32s3`), 16 Mo de flash, 8 Mo de PSRAM
octale. Le SoC intègre une radio Wi-Fi 2,4 GHz **et** un contrôleur Bluetooth
LE : BLE ne demande aucun composant supplémentaire.

**Table de partitions (relue dans le build).** Deux emplacements applicatifs de
même taille, plus les métadonnées OTA — c'est déjà une disposition à double
banque, prête pour l'OTA :

| Partition | Type / sous-type | Taille |
|---|---|---|
| `otadata`  | data / ota  | 0x2000 (8 Ko) |
| `phy_init` | data / phy  | 0x1000 |
| `app0`     | app / ota_0 | 0x7C0000 (~7,75 Mo) |
| `app1`     | app / ota_1 | 0x7C0000 (~7,75 Mo) |
| `nvs`      | data / nvs  | 0x70000 (448 Ko) |

Une image applicative écrite par BLE suit donc exactement le même chemin qu'une
image Wi-Fi : écriture dans la banque **inactive** (`ota_0`/`ota_1`), puis bascule
via `otadata`. Aucune nouvelle partition n'est requise. La taille d'image est
plafonnée par la banque libre (~7,75 Mo), très au-dessus du binaire actuel.

**Budget mémoire vive et profondeur du tampon circulaire.** C'est la contrainte
dimensionnante, et elle fixe directement la profondeur du tampon de réception
(§3). Dans le build courant le contrôleur Bluetooth est **désactivé**
(`CONFIG_BT_ENABLED` non positionné) : l'activer réserve la RAM du contrôleur
BLE et de la pile hôte, qui vient s'ajouter à la chaîne vocale (modèle d'éveil
`micro_wake_word`, tampons audio I2S, pile Wi-Fi/API). Le modèle et les tampons
audio résident en PSRAM, mais les piles réseau consomment de la RAM interne.
Deux règles de conception en découlent : (a) n'activer la pile BLE **que**
pendant une session de mise à jour, pas en permanence ; (b) retenir la pile
hôte **NimBLE** plutôt que Bluedroid, sensiblement plus économe en RAM — à
confirmer par une mesure de tas libre au moment de l'implémentation.

Le tampon circulaire de réception (§3) découple la réception radio de
l'écriture flash. Sa profondeur **n'est pas fixée en dur** : elle se déduit du
budget RAM. Avec un slot par SDU de 2048 octets, *N* slots occupent `N × 2048`
octets de RAM interne, *N* étant pris dans la marge encore libre une fois la
pile BLE montée et la session ouverte Wi-Fi éteint. En posant l'hypothèse — **à
valider par une mesure de tas libre**, non mesurée ici puisque le BT n'est pas
compilé — d'une enveloppe de 32 à 64 Ko allouable à ce tampon, *N* tombe entre
16 et 32 slots. On retient **N = 16 (32 Ko)** comme valeur prudente : assez pour
absorber plusieurs fenêtres de crédits (§3) sans famine côté flash, à re-régler
contre le tas réellement mesuré. Le débit d'écriture flash dépassant le débit RF
BLE, ce tampon lisse les à-coups plutôt qu'il ne stocke durablement.

**Coexistence radio BLE/Wi-Fi.** Wi-Fi et BLE partagent l'antenne 2,4 GHz.
L'arbitrage de coexistence logicielle est compilé dans le build courant
(`CONFIG_ESP_COEX_ENABLED=y`), ce qui autorise le fonctionnement simultané, mais
au prix d'un partage de temps d'antenne qui réduit le débit des deux liens. La
conception en tient compte en **n'exigeant jamais** BLE et Wi-Fi actifs en même
temps : le cas d'usage d'amorçage se fait Wi-Fi éteint, le cas de récupération
aussi. Le débit BLE atteignable par canal L2CAP (§3) — de l'ordre de la
centaine de Ko/s selon l'intervalle de connexion et le PHY négociés — donne une
à quelques minutes pour une image de plusieurs méga-octets, acceptable pour un
chemin de secours.

## 3. Transport : canal L2CAP orienté connexion (LE CoC)

Le transport **n'est pas** un service GATT. GATT/ATT impose un en-tête et, pour
un flux fiable, un aller-retour d'acquittement par écriture : ce surcoût par PDU
plafonne le débit sur un transfert de plusieurs méga-octets. La conception
retient donc un **canal L2CAP orienté connexion** (LE Connection-Oriented
Channel, CoC), conçu pour écouler efficacement de gros blocs avec un contrôle
de flux natif par crédits.

**PSM et rôles.** Le terminal est le **périphérique**, le téléphone ou le poste
d'exploitation le **central**. Deux PSM LE dynamiques (plage 0x0080–0x00FF
réservée par le cœur Bluetooth aux PSM alloués dynamiquement) portent des rôles
distincts :

| PSM LE | Rôle | Cycle de vie |
|---|---|---|
| **0x0081** | Amorçage : échange de jeton + ECDH pour dériver le matériel d'authentification (§4) | une fois par cycle de vie du *bond* |
| **0x0080** | Flux de l'image OTA | à chaque session, après lien chiffré niveau 4 |

**SDU, MPS et réassemblage.** Le flux d'image passe par le canal 0x0080. La
**SDU** (unité de données applicative) est fixée à **2048 octets**. Le
découpage en paquets n'est **pas** géré par l'application : L2CAP CoC mène sa
propre négociation de MTU/MPS, segmente chaque SDU de 2048 octets en trames
K-frames de la taille MPS supportée par le pair, puis les réassemble à la
réception. L'application émet et reçoit des SDU entières — elle est agnostique
à la segmentation.

**Contrôle de flux par crédits (natif) et chaîne de réception.** Chaîne :
`canal CoC → tampon circulaire (N = 16 SDU) → écriture flash en flux`. LE CoC
intègre un mécanisme de **crédits** — chaque crédit autorise une trame : le
périphérique n'en accorde qu'à hauteur de la place libre dans le tampon (§2) et
en re-crédite le central à mesure qu'il vide le tampon vers la flash. Le débit
RF est ainsi asservi à la vitesse d'écriture sans acquittement applicatif : le
flux ralentit de lui-même si la flash prend du retard et ne déborde jamais le
tampon. Un condensé cumulatif est calculé au fil de l'eau pour détecter une
corruption avant la fin du transfert plutôt qu'après.

## 4. Intégrité et sécurité

**Niveau de liaison exigé : LE Security Mode 1 Level 4** — LE Secure Connections
(LESC, ECDH sur P-256), avec protection **MITM** *et* **bonding** tous deux
**obligatoires**. Le flux d'image (0x0080) ne s'ouvre que sur un lien déjà
chiffré à ce niveau.

**Le problème de l'authentification MITM sans écran ni clavier.** L'appairage
MITM classique suppose un canal utilisateur (comparaison de nombres, saisie de
code). Le terminal n'a ni écran de saisie ni clavier. La MITM est donc obtenue
par la **voie OOB** (Out-Of-Band), amorcée par un canal dédié :

1. À la première mise en relation (appareil non encore *bondé*), le central
   ouvre le canal d'amorçage **0x0081**.
2. Les deux extrémités échangent un jeton et calculent une **clé partagée par
   ECDH**. Cet ECDH est **ancré par du matériel provisionné en usine** : le
   terminal détient une clé pré-provisionnée gravée à la fabrication. Ce n'est
   **pas** un modèle « confiance à la première connexion » (TOFU) : sans le
   matériel d'usine, un tiers ne peut pas calculer la clé partagée attendue.
3. La clé partagée sert de **matériel OOB** pour piloter l'appairage LESC avec
   MITM et bonding. Le lien est alors chiffré niveau 4.
4. Le canal 0x0081 est **fermé** ; le *bond* est enregistré.
5. 0x0080 s'ouvre sur ce lien niveau 4 et le transfert commence.

**Cycle de vie du canal d'amorçage.** 0x0081 est utilisé **exactement une fois**
par cycle de vie du bond. Toutes les reconnexions ultérieures s'appuient sur le
*bond* : le lien niveau 4 est rétabli à partir du bond, et **0x0080 s'ouvre
directement**, sans repasser par 0x0081. Si le bond est supprimé (réinitialisation
usine ou effacement de clé), 0x0081 est **ré-activé** pour un nouvel amorçage.

**Modèle de menace, ancré sur le matériel d'usine.**

- **Image falsifiée / « evil-maid » et MITM d'appairage** : un tiers à portée,
  y compris un attaquant au milieu, ne peut pas compléter l'appairage
  authentifié sans le matériel provisionné en usine (il ne connaît pas la clé
  partagée dérivée), donc n'ouvre jamais 0x0080. En défense en profondeur,
  l'image reçue est en outre vérifiée par **signature Ed25519** (clé publique
  intégrée au firmware, clé privée hors appareil) avant toute bascule `otadata`.
- **Retour de version (« downgrade »)** : refus applicatif de toute image dont
  la version (`esp_app_desc_t`) est inférieure à la version courante. Le
  mécanisme matériel d'anti-rollback est **désactivé** dans le build courant
  (`CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK` non positionné) et documenté comme
  durcissement optionnel (comptage monotone en eFuse, irréversible).
- **Déni de service en cours de transfert** : une coupure ne touche que la
  banque **inactive** ; la banque active reste amorçable et aucune bascule n'a
  lieu sans image complète, signée et de version valide (voir §5).

**Durcissement matériel disponible mais non activé.** Secure Boot v2 (RSA) est
**supporté** par la puce et le build (`CONFIG_SECURE_BOOT_V2_RSA_SUPPORTED=y`)
mais **non activé** (`CONFIG_SECURE_BOOT` non positionné). La signature Ed25519
est retenue comme socle (réversible, testable au banc) ; Secure Boot v2 est
documenté comme durcissement ultérieur, son activation étant irréversible
(brûlage d'eFuses) et décidée séparément.

## 5. Robustesse

**Reprise après déconnexion.** Le décalage du dernier bloc **validé et écrit**
en flash est conservé par le périphérique. À la reconnexion (lien niveau 4
rétabli depuis le bond, réouverture de 0x0080), le central lit ce décalage et
**reprend** l'émission à partir de là : le canal CoC est recréé, les crédits
ré-accordés selon la place du tampon, et le transfert repart sans repartir de
zéro. La session est identifiée pour qu'un central différent ne reprenne pas
par erreur un transfert entamé.

**Bascule à double banque et retour arrière au démarrage.** La disposition
`ota_0`/`ota_1` + `otadata` permet le schéma standard ESP-IDF, et le retour
arrière logiciel au boot est **activé** dans le build courant
(`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`, `CONFIG_APP_ROLLBACK_ENABLE=y`) :

1. L'image reçue est écrite dans la banque inactive, puis — après vérification
   de signature et de version — marquée comme candidate au prochain démarrage.
2. Au redémarrage, le bootloader lance l'image candidate dans l'état
   « en attente de validation ».
3. Le firmware ne se déclare valide **qu'après** avoir vérifié ses propres
   fonctions vitales (Wi-Fi remonté, API montée, chaîne audio initialisée),
   suivant le schéma `esp_ota_mark_app_valid_cancel_rollback`.
4. S'il redémarre ou se fige avant de se confirmer, le bootloader **revient
   automatiquement** à la banque précédente au démarrage suivant. Une image qui
   « boote mais ne fonctionne pas » ne condamne donc pas l'appareil.

**Chien de garde.** Le compte à rebours de validation doit tenir compte du chien
de garde matériel : la fenêtre d'auto-vérification est plus courte que le délai
du watchdog, sinon un firmware sain mais lent à démarrer serait interprété comme
défaillant. La validation est déclenchée par un critère fonctionnel atteint, pas
par une simple temporisation.

## 6. Estimation d'effort et plan de validation

Découpage réaliste (ordre de grandeur, développeur unique) :

| Phase | Contenu | Effort indicatif |
|---|---|---|
| P1 | Pile NimBLE + canal L2CAP CoC 0x0080, SDU 2048 + tampon circulaire, transfert en banque inactive (sans sécurité) | ~4–5 j |
| P2 | Signature Ed25519 + contrôle de version applicatif | ~2–3 j |
| P3 | Amorçage 0x0081 : ECDH ancré usine, appairage LESC/MITM/bonding par OOB, cycle de vie du bond | ~3–4 j |
| P4 | Reprise après déconnexion (reprise CoC + crédits + décalage validé) | ~2 j |
| P5 | Retour arrière au boot piloté par auto-vérification, réglage watchdog | ~2 j |
| P6 | Validation au banc + en conditions réelles (HIL) | ~2–3 j |

**Risque de validation à lever en premier : disponibilité du L2CAP CoC.** Le
support des canaux L2CAP orientés connexion côté ESP32-S3 dépend de la version
d'ESP-IDF et de la configuration NimBLE (nombre de canaux CoC, MPS). C'est la
dépendance la plus structurante du plan, à **confirmer au tout début de P1** par
un court prototype ouvrant un CoC entre le terminal et un central de test, avant
d'engager le reste.

**Plan de validation.**

- *Banc* : transfert nominal, MTU/MPS négociés vérifiés, crédits observés,
  débit et durée mesurés ; injection de fautes — coupure de lien à mi-transfert
  (reprise correcte via décalage validé), image tronquée (rejetée), signature
  invalide (rejetée), image de version inférieure (rejetée).
- *Sécurité* : vérifier qu'un central sans le matériel d'usine échoue
  l'appairage et n'ouvre jamais 0x0080 ; qu'après bonding une reconnexion ouvre
  0x0080 directement sans repasser par 0x0081 ; qu'un effacement de bond
  ré-active 0x0081.
- *Retour arrière (HIL)* : flasher volontairement une image qui démarre mais
  échoue son auto-vérification, et confirmer le retour automatique à la banque
  précédente — le test qui prouve qu'une mauvaise mise à jour n'immobilise pas
  le terminal.
- *Coexistence* : vérifier qu'une session BLE Wi-Fi éteint n'altère pas l'état
  d'éveil et que la chaîne vocale reprend normalement après la session.

**Rappel de la décision de réduction de périmètre.** Sur les quatre semaines du
sprint, la voie Wi-Fi OTA existante couvre l'intégralité du besoin d'exploitation
du MVP (terminal sur le réseau du foyer). La voie BLE apporte l'amorçage et la
récupération, à valeur réelle mais non critiques pour la démonstration ; leur
coût (pile BLE, transport L2CAP, cryptographie d'appairage, tests d'injection de
fautes) est sans rapport avec ce gain sur l'itération courante. La conception est
donc figée ici plutôt que subie en fin de sprint.

---

**Réserve de vérification.** Les faits de configuration matérielle (table de
partitions, options `sdkconfig` : rollback activé, anti-rollback et Secure Boot
désactivés, contrôleur BT désactivé, coexistence activée, flash 16 Mo) ont été
relus dans le build `coach-terminal` du 2026-07-24. Les mécanismes BLE cités —
canal L2CAP orienté connexion (LE CoC), crédits, SDU/MPS, LESC, MITM, bonding,
voie OOB, ECDH, plage de PSM LE dynamique — relèvent de la spécification cœur
Bluetooth et de l'API OTA publique d'ESP-IDF (`esp_ota_*`, `esp_app_desc_t`).
En revanche, **les symboles C spécifiques de NimBLE (API `ble_l2cap_*`,
configuration du gestionnaire de sécurité pour l'OOB, `CONFIG_BT_NIMBLE_*`) et
la disponibilité même du L2CAP CoC sur la version d'ESP-IDF figée n'ont pas pu
être relus en session** : le contrôleur BT n'étant pas compilé dans ce build,
ni les en-têtes NimBLE ni `esp_ota_ops.h` ne sont présents dans l'arborescence.
Ces noms d'API et ces symboles `CONFIG_*` sont donc à confirmer sur la version
d'ESP-IDF/NimBLE retenue au moment de l'implémentation (voir le risque de
validation P1 au §6).
