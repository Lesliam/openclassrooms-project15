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

**Budget mémoire vive.** C'est la contrainte dimensionnante. Dans le build
courant le contrôleur Bluetooth est **désactivé** (`CONFIG_BT_ENABLED` non
positionné) : l'activer réserve la RAM du contrôleur BLE et de la pile hôte,
qui vient s'ajouter à la chaîne vocale (modèle d'éveil `micro_wake_word`,
tampons audio I2S, pile Wi-Fi/API). Le modèle et les tampons audio résident en
PSRAM, mais les piles réseau consomment de la RAM interne. Deux règles de
conception en découlent : (a) n'activer la pile BLE **que** pendant une session
de mise à jour, pas en permanence ; (b) retenir la pile hôte **NimBLE** plutôt
que Bluedroid, sensiblement plus économe en RAM pour un rôle périphérique GATT
seul — à confirmer par une mesure de tas libre au moment de l'implémentation.

**Coexistence radio BLE/Wi-Fi.** Wi-Fi et BLE partagent l'antenne 2,4 GHz.
L'arbitrage de coexistence logicielle est compilé dans le build courant
(`CONFIG_ESP_COEX_ENABLED=y`), ce qui autorise le fonctionnement simultané, mais
au prix d'un partage de temps d'antenne qui réduit le débit des deux liens. La
conception en tient compte en **n'exigeant jamais** BLE et Wi-Fi actifs en même
temps : le cas d'usage d'amorçage se fait Wi-Fi éteint, le cas de récupération
aussi. Le débit BLE atteignable (quelques dizaines à ~100 Ko/s selon la
négociation) donne un ordre de grandeur d'une à quelques minutes pour une image
de plusieurs méga-octets — acceptable pour un chemin de secours.

## 3. Conception du service GATT

Le terminal joue le rôle de **périphérique** GATT ; le téléphone ou le poste
d'exploitation est le **central**. Un service GATT dédié à l'OTA expose trois
caractéristiques :

| Caractéristique | Propriétés | Rôle |
|---|---|---|
| **Control Point** | Write, Notify | Commandes (début, fin, abandon) + acquittements et codes d'erreur |
| **Data** | Write Without Response | Flux des blocs de firmware |
| **Status / Progress** | Read, Notify | État courant, dernier décalage validé, reprise |

**Négociation de MTU et découpage.** Le central négocie le MTU ATT juste après
connexion. Chaque bloc de données est dimensionné à `MTU − 3` octets (les trois
octets d'en-tête ATT), afin d'émettre un bloc par PDU sans fragmentation L2CAP.
Le firmware ne suppose pas un MTU donné : il lit la valeur négociée et
l'annonce dans la caractéristique Status.

**Contrôle de flux.** Le débit passe par des écritures *Write Without Response*
(pas d'acquittement applicatif par bloc, sinon le débit s'effondre). Le
contrôle de flux est assuré par un mécanisme de **crédits** : le périphérique
publie via Notify le nombre de blocs qu'il peut encore absorber (fonction de la
place tampon et de la vitesse d'écriture flash) ; le central ne dépasse pas ce
solde. Toutes les *N* fenêtres de crédits, un condensé cumulatif est comparé
pour détecter une corruption au fil de l'eau plutôt qu'à la fin.

**Machine à états.** Le Control Point pilote une machine à états explicite :

```
   idle ── start ─▶ receiving ── (dernier bloc) ─▶ validating
     ▲                 │                              │
     │                 │ abandon / perte lien         │ échec signature/version
     │                 ▼                              ▼
     └──────────────  idle  ◀───────────────────────  (rejet, banque inactive effacée)
                                        │ succès
                                        ▼
                                    applying ── reboot ─▶ (banque candidate)
                                        │
                                        ▼
                                   rollback  (si le nouveau firmware ne se valide pas au boot — voir §5)
```

## 4. Intégrité et sécurité

Le modèle de menace retenu, pour un objet posé sur un bureau et mis à jour par
radio de proximité :

- **Image falsifiée / « evil-maid »** : un tiers pousse un firmware modifié.
- **Retour de version (« downgrade »)** : réintroduire une version ancienne
  vulnérable, correctement signée à l'époque.
- **Déni de service en cours de transfert** : couper le lien pour laisser
  l'appareil dans un état instable.

Réponses de conception :

- **Signature d'image.** Deux niveaux possibles. (a) *Applicatif* : signature
  Ed25519 de l'image, vérifiée par le firmware avant la bascule `otadata` ; la
  clé publique est intégrée au firmware, la clé privée reste hors appareil.
  (b) *Chaîne matérielle* : Secure Boot v2 (RSA), **supporté** par la puce et le
  build (`CONFIG_SECURE_BOOT_V2_RSA_SUPPORTED=y`) mais **non activé**
  aujourd'hui (`CONFIG_SECURE_BOOT` non positionné). La conception recommande la
  signature applicative Ed25519 comme socle (réversible, testable au banc) et
  documente Secure Boot v2 comme durcissement ultérieur — son activation est
  **irréversible** (brûlage d'eFuses) et doit être décidée séparément.
- **Anti-retour de version.** L'en-tête d'image ESP-IDF (`esp_app_desc_t`) porte
  un champ de version sécurisée. Le mécanisme matériel d'anti-rollback est
  **désactivé** dans le build courant (`CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK`
  non positionné). La conception impose au minimum un **contrôle de version
  applicatif** — refuser une image dont la version est inférieure à celle en
  cours — et signale l'anti-rollback matériel (comptage monotone en eFuse) comme
  option, elle aussi irréversible.
- **Appairage authentifié.** Une session OTA n'est ouverte qu'après appairage
  BLE avec *bonding* (LE Secure Connections). L'échange de firmware n'est jamais
  accepté sur un lien non appairé, ce qui écarte l'écriture par un central
  arbitraire à portée.
- **Robustesse au DoS.** Une coupure en cours de transfert ne touche que la
  banque **inactive** ; la banque active reste amorçable. Un transfert
  incomplet ou non validé n'entraîne jamais de bascule (voir §5).

## 5. Robustesse

**Reprise après déconnexion.** Le décalage du dernier bloc écrit en flash est
publié dans la caractéristique Status. À la reconnexion, le central lit ce
décalage et **reprend** l'émission à partir de là, sans recommencer le
transfert. La session est identifiée pour qu'un central différent ne reprenne
pas par erreur un transfert entamé.

**Bascule à double banque et retour arrière au démarrage.** La disposition
`ota_0`/`ota_1` + `otadata` permet le schéma standard ESP-IDF, et le retour
arrière logiciel au boot est **activé** dans le build courant
(`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`, `CONFIG_APP_ROLLBACK_ENABLE=y`) :

1. L'image reçue est écrite dans la banque inactive, puis marquée comme
   candidate au prochain démarrage.
2. Au redémarrage, le bootloader lance l'image candidate dans l'état
   « en attente de validation ».
3. Le firmware ne se déclare valide **qu'après** avoir vérifié ses propres
   fonctions vitales (Wi-Fi remonté, API montée, chaîne audio initialisée). Ce
   n'est qu'alors qu'il confirme l'image (schéma
   `esp_ota_mark_app_valid_cancel_rollback`).
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
| P1 | Service GATT + machine à états, transfert en banque inactive (sans sécurité) | ~3–4 j |
| P2 | Signature Ed25519 + contrôle de version applicatif | ~2–3 j |
| P3 | Appairage/bonding, reprise après déconnexion, crédits de flux | ~2–3 j |
| P4 | Retour arrière au boot piloté par auto-vérification, réglage watchdog | ~2 j |
| P5 | Validation au banc + en conditions réelles (HIL) | ~2–3 j |

**Plan de validation.**

- *Banc* : transfert nominal, MTU négocié vérifié, débit et durée mesurés ;
  injection de fautes — coupure de lien à mi-transfert (reprise correcte),
  image tronquée (rejetée), signature invalide (rejetée), image de version
  inférieure (rejetée).
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
coût (pile BLE, sécurité cryptographique, tests d'injection de fautes) est sans
rapport avec ce gain sur l'itération courante. La conception est donc figée ici,
prête à être implémentée dans une itération ultérieure, plutôt que subie en fin
de sprint.

---

**Réserve de vérification.** Les faits de configuration matérielle (table de
partitions, options `sdkconfig` : rollback activé, anti-rollback et Secure Boot
désactivés, contrôleur BT désactivé, coexistence activée, flash 16 Mo) ont été
relus dans le build `coach-terminal` du 2026-07-24. Les **noms d'API C**
ESP-IDF (`esp_ota_*`, `esp_app_desc_t`) et les propriétés GATT relèvent de l'API
publique stable d'ESP-IDF et du profil BLE ; leurs signatures exactes et les
symboles `CONFIG_*` à activer sont à confirmer sur la version d'ESP-IDF figée au
moment de l'implémentation, l'en-tête `esp_ota_ops.h` n'ayant pas pu être relu
dans l'arborescence de build lors de la rédaction.
