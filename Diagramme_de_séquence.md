
## 1. UC-AUTH-01 — Login + CGU + première connexion

![[Pasted image 20260106171208.png]]
```plantuml
@startuml
title UC-AUTH-01 — Login + CGU + première connexion
actor Visiteur as V
participant "Web" as WEB
participant "AuthController" as AUTH
database "DB" as DB
participant "Session" as S

V -> WEB : GET /login
WEB --> V : Form (CSRF)

V -> WEB : POST /login (email,password,CSRF)
WEB -> AUTH : authenticate()
AUTH -> AUTH : throttle check
AUTH -> DB : SELECT user by email
DB --> AUTH : user(hash, active, cgu_ok, first_login_at)
AUTH -> AUTH : verifyPassword()

alt ok AND active
  AUTH -> S : login(user_id)
  AUTH -> S : regenerate session id
  AUTH -> DB : UPDATE users set first_login_at=now WHERE first_login_at IS NULL
  alt cgu_ok=false
    AUTH --> WEB : redirect /cgu
    WEB --> V : Page CGU (CSRF)
    V -> WEB : POST /cgu/accept (CSRF)
    WEB -> DB : UPDATE users set cgu_ok=true, cgu_accepted_at=now
    WEB --> V : redirect /home
  else cgu_ok=true
    AUTH --> WEB : redirect /home
  end
else ko OR inactive
  AUTH --> WEB : redirect /login (generic error)
end
@enduml
```

Scénario textuel (UC-AUTH-01)

- Préconditions : utilisateur existe ; champs `password_hash`, `active`, `cgu_ok`, `first_login_at` présents.
- Déclencheur : POST `/login` avec CSRF.
- Nominal : throttle → lecture user → vérification mot de passe → contrôle `active` → ouverture session + régénération ID → `first_login_at` renseigné si NULL → si `cgu_ok=false` redirection `/cgu` puis POST `/cgu/accept` met `cgu_ok=true` et `cgu_accepted_at` → redirection `/home`.
- Alternative : identifiants invalides OU compte inactif → redirection `/login` avec erreur générique.
- Postconditions : session active ; `first_login_at` mis si absent ; CGU tracées uniquement si acceptées.

## 2. UC-AUTH-02 — Mot de passe perdu / reset

```plantuml
@startuml
title UC-AUTH-02 — Mot de passe perdu / réinitialisation
actor Visiteur as V
participant "Web" as WEB
participant "PasswordController" as PWD
database "DB" as DB
participant "Mail" as MAIL

V -> WEB : GET /password/forgot
WEB --> V : Form email (CSRF)

V -> WEB : POST /password/forgot(email,CSRF)
WEB -> PWD : requestReset()
PWD -> PWD : throttle check
PWD -> DB : SELECT user by email

alt user trouvé
  PWD -> PWD : generate token
  PWD -> DB : INSERT password_resets(token_hash, user_id, expires_at)
  PWD -> MAIL : send reset link(token)
end
WEB --> V : message générique (anti-énumération)

V -> WEB : GET /password/reset?token=...
WEB --> V : Form new password (CSRF)

V -> WEB : POST /password/reset(token,new_password,CSRF)
WEB -> PWD : reset()
PWD -> DB : SELECT reset WHERE token_hash=HASH(token) AND expires_at>now

alt token valide
  PWD -> DB : UPDATE users set password_hash=...
  PWD -> DB : DELETE password_resets row
  WEB --> V : redirect /login
else invalide/expiré
  WEB --> V : erreur
end
@enduml
```

Scénario textuel (UC-AUTH-02)

- Préconditions : service mail ; table `password_resets` avec `token_hash` et `expires_at`.
- Déclencheur : POST `/password/forgot` avec CSRF.
- Nominal : throttle → recherche user → si trouvé génération token → insertion `token_hash` + expiration → envoi mail → affichage message générique → formulaire reset → POST `/password/reset` vérifie `HASH(token)` et expiration → mise à jour `password_hash` → suppression ligne reset → redirection login.
- Alternative : email inconnu → aucun insert / aucun mail ; même message générique.
- Alternative : token invalide/expiré → erreur.
- Postconditions : mot de passe modifié uniquement si token valide ; token invalidé par suppression.

## UC-USER-IMP-01 — Importer une promotion (cohorte) depuis un export Pronote.

```plantuml
@startuml
title UC-USER-IMP-01 — Import promotion (Pronote CSV) + validation + création
actor Admin as ADM
participant "Web" as WEB
participant "ImportPromotionController" as IPC
participant "Policy(Users)" as POL
participant "PronoteParser" as PARSER
participant "ImportValidator" as VAL
database "DB" as DB
participant "Audit" as AUD

ADM -> WEB : GET /admin/imports/pronote
WEB --> ADM : Form upload (CSRF)

ADM -> WEB : POST /admin/imports/pronote/preview(file,CSRF)
WEB -> IPC : preview(file)
IPC -> POL : authorize(importPromotion)
alt ok
  IPC -> PARSER : parseCSV(file)
  PARSER --> IPC : rows[]
  IPC -> VAL : validate(rows)
  VAL --> IPC : report(errors,warnings,stats)
  IPC --> WEB : 200 preview(report)
  WEB --> ADM : tableau + erreurs + "confirmer"
else ko
  WEB --> ADM : 403
end

ADM -> WEB : POST /admin/imports/pronote/commit(file,CSRF)
WEB -> IPC : commit(file)
IPC -> POL : authorize(importPromotion)
alt ok
  IPC -> PARSER : parseCSV(file)
  PARSER --> IPC : rows[]
  IPC -> VAL : validate(rows)
  VAL --> IPC : report(errors,warnings,stats)

  alt errors = 0
    IPC -> DB : BEGIN
    loop pour chaque ligne
      IPC -> DB : UPSERT user (student)\n(match: student_id/ine/email)
      IPC -> DB : UPSERT enrollment (promotion/classe)\n(attache student -> promo)
    end
    IPC -> AUD : write audit(import_promotion, stats, actor=ADM)
    IPC -> DB : COMMIT
    IPC --> WEB : 201 résultat(stats)
    WEB --> ADM : succès
  else errors > 0
    IPC --> WEB : 422 report(errors)
    WEB --> ADM : échec (aucune écriture)
  end
else ko
  WEB --> ADM : 403
end
@enduml

```

Scénario textuel (UC-USER-IMP-01) — strictement conforme au diagramme

- Préconditions : Admin authentifié ; droit `importPromotion` ; endpoint upload actif ; CSV Pronote disponible.
- Déclencheur 1 : POST `/admin/imports/pronote/preview` avec fichier + CSRF.
- Nominal 1 (prévisualisation) : autorisation `importPromotion` → parse CSV → validation (erreurs/avertissements/stats) → retour preview.
- Déclencheur 2 : POST `/admin/imports/pronote/commit` avec fichier + CSRF.
- Nominal 2 (commit) : autorisation `importPromotion` → parse CSV → validation → si `errors=0` alors transaction DB : UPSERT étudiants (clé de correspondance définie) + UPSERT d’inscription à la promotion/classe → écriture d’audit → commit → retour succès.
- Alternative A : policy refuse (preview ou commit) → 403.
- Alternative B : validation renvoie `errors>0` au moment du commit → 422 avec report, et aucune écriture DB (pas de transaction).
- Postconditions : en succès, les étudiants sont créés/mis à jour et rattachés à la promotion ; une trace d’audit d’import existe.

## 3. UC-STAGE-01 — Étudiant gère “Mes stages”
    

```plantuml
@startuml
title UC-STAGE-01 — Étudiant : gérer "Mes stages"
actor Étudiant as E
participant "Web" as WEB
participant "StageController" as STC
participant "Policy(Stage)" as POL
database "DB" as DB

E -> WEB : GET /my-stages
WEB -> STC : indexMy()
STC -> DB : SELECT stages WHERE student_id=me
WEB --> E : liste

E -> WEB : POST /my-stages (payload,CSRF)
WEB -> STC : store()
STC -> POL : authorize(create)
alt ok
  STC -> DB : INSERT stage(student_id=me,...)
  WEB --> E : 201 + redirect détail
else ko
  WEB --> E : 403
end

E -> WEB : PUT /my-stages/{id} (payload,CSRF)
WEB -> STC : update(id)
STC -> DB : SELECT stage WHERE id=? AND student_id=me
alt trouvé
  STC -> POL : authorize(update, stage)
  alt ok
    STC -> DB : UPDATE stage WHERE id=? AND student_id=me
    WEB --> E : 200
  else ko
    WEB --> E : 403
  end
else absent
  WEB --> E : 404
end
@enduml
```

Scénario textuel (UC-STAGE-01)

- Préconditions : utilisateur authentifié ; rôle étudiant.
- Déclencheur : GET `/my-stages`, POST `/my-stages`, PUT `/my-stages/{id}`.
- Nominal : liste des stages filtrée par `student_id=me` → création autorisée → mise à jour d’un stage après chargement “scopé” (`id` + `student_id=me`) et autorisation policy.
- Alternatives : create/update refusés par policy → 403 ; update sur un id non appartenant (non trouvé via scoping) → 404 ; update sur stage trouvé mais policy refuse → 403.
- Postconditions : stage créé/modifié uniquement dans le périmètre de l’étudiant.

## 4. UC-STAGE-02 — Prof/Admin : gérer stages + affectations

```plantuml
@startuml
title UC-STAGE-02 — Prof/Admin : gérer stages + affectations
actor Professeur as P
participant "Web" as WEB
participant "StageController" as STC
participant "Policy(Stage)" as POL
database "DB" as DB

P -> WEB : GET /stages?filters...
WEB -> STC : index(filters)
STC -> POL : authorize(viewAny)
alt ok
  STC -> DB : SELECT stages + joins(student,company)
  WEB --> P : liste
else ko
  WEB --> P : 403
end

P -> WEB : POST /stages (payload,CSRF)
WEB -> STC : store()
STC -> POL : authorize(create)
alt ok
  STC -> DB : BEGIN
  STC -> DB : INSERT stage(...)
  STC -> DB : INSERT/UPDATE affectations(tuteur,pp,...)
  STC -> DB : COMMIT
  WEB --> P : 201 + détail
else ko
  WEB --> P : 403
end
@enduml
```

Scénario textuel (UC-STAGE-02)

- Préconditions : rôle prof/admin ; référentiels étudiants/entreprises disponibles.
- Déclencheur : GET `/stages`, POST `/stages` avec CSRF.
- Nominal : `viewAny` autorise la liste → création autorisée → transaction DB : insertion stage puis insertion/MAJ affectations → commit → retour détail.
- Alternatives : `viewAny` refuse → 403 ; `create` refuse → 403.
- Postconditions : aucun stage “partiel” (transaction) ; affectations cohérentes avec le stage.

## 5. UC-DOC-01 — Générer / télécharger convention
    

```plantuml
@startuml
title UC-DOC-01 — Convention : générer / télécharger (PDF)
actor "Étudiant/Prof" as A
participant "Web" as WEB
participant "DocumentController" as DOC
participant "Policy(Stage)" as POL
database "DB" as DB
participant "PDF Renderer" as PDF
participant "Storage" as FS

A -> WEB : GET /stages/{id}/convention
WEB -> DOC : generateConvention(stage_id)
DOC -> DB : SELECT stage + student + company + contacts
DOC -> POL : authorize(view, stage)

alt authorized
  alt data complete
    DOC -> PDF : render(template,data)
    PDF --> DOC : bytes
    DOC -> FS : store(bytes)
    DOC --> WEB : file response (pdf)
    WEB --> A : téléchargement
  else data missing
    DOC --> WEB : 422 + liste champs manquants
    WEB --> A : erreur
  end
else forbidden
  WEB --> A : 403
end
@enduml
```

Scénario textuel (UC-DOC-01)

- Préconditions : stage existant ; template ; stockage disponible.
- Déclencheur : GET `/stages/{id}/convention`.
- Nominal : lecture des données → autorisation `view` → si données complètes : rendu PDF → stockage → réponse fichier.
- Alternatives : autorisation refusée → 403 ; données incomplètes → 422 + champs manquants.
- Postconditions : un PDF n’est produit que si l’accès est autorisé et les données sont complètes.

## 6. UC-ENT-01 — Import/MAJ entreprise via SIRET
    

```plantuml
@startuml
title UC-ENT-01 — Entreprise : import/MAJ via SIRET (API)
actor "Prof/Admin" as A
participant "Web" as WEB
participant "CompanyController" as C
participant "Policy(Company)" as POL
participant "SireneClient" as API
database "DB" as DB

A -> WEB : POST /companies/import (siret,CSRF)
WEB -> C : importBySiret(siret)
C -> POL : authorize(import)
alt ok
  C -> DB : SELECT company WHERE siret=?
  alt exists
    C -> DB : UPDATE company (merge strategy)
    WEB --> A : fiche entreprise
  else new
    C -> API : GET company(siret)
    alt api ok
      API --> C : data
      C -> DB : INSERT company + meta(source=sirene)
      WEB --> A : fiche entreprise
    else api error
      C --> WEB : 503 (api unavailable)
      WEB --> A : erreur
    end
  end
else ko
  WEB --> A : 403
end
@enduml
```

Scénario textuel (UC-ENT-01)

- Préconditions : rôle prof/admin ; accès API ; stratégie de fusion (merge) définie.
- Déclencheur : POST `/companies/import` avec CSRF.
- Nominal : autorisation `import` → recherche par SIRET → si existe : MAJ selon stratégie → fiche ; sinon appel API → si OK insertion entreprise + meta source → fiche.
- Alternatives : policy refuse → 403 ; API en erreur → 503.
- Postconditions : entreprise créée/MAJ uniquement si autorisée ; échec API n’écrit rien.

## 7. UC-ENT-02 — Ajout manuel + validation

```plantuml
@startuml
title UC-ENT-02 — Entreprise : ajout manuel + validation
actor "Étudiant/Prof" as S
actor "Admin" as ADM
participant "Web" as WEB
participant "CompanyController" as C
participant "ValidationController" as V
participant "Policy(Validation)" as POLV
database "DB" as DB
participant "Mail" as MAIL

S -> WEB : POST /companies (payload,CSRF)
WEB -> C : store()
C -> DB : INSERT company(status=pending, created_by=S)
C -> DB : INSERT validation_request(type=company,target_id,status=pending)
C -> MAIL : notify admins
WEB --> S : 202 (en attente)

ADM -> WEB : GET /validations
WEB -> V : index()
V -> POLV : authorize(viewAny)
alt ok
  V -> DB : SELECT pending validations
  WEB --> ADM : liste
else ko
  WEB --> ADM : 403
end

ADM -> WEB : POST /validations/{id}/approve (CSRF)
WEB -> V : approve(id)
V -> POLV : authorize(approve)
alt ok
  V -> DB : UPDATE company set status=active
  V -> DB : UPDATE validation_request set status=approved
  V -> MAIL : notify requester
  WEB --> ADM : 200
else ko
  WEB --> ADM : 403
end

ADM -> WEB : POST /validations/{id}/reject (reason,CSRF)
WEB -> V : reject(id,reason)
V -> POLV : authorize(reject)
alt ok
  V -> DB : UPDATE validation_request set status=rejected, reason=...
  V -> DB : UPDATE company set status=rejected
  V -> MAIL : notify requester
  WEB --> ADM : 200
else ko
  WEB --> ADM : 403
end
@enduml
```

Scénario textuel (UC-ENT-02)

- Préconditions : états `pending/active/rejected` ; file validations ; mail opérationnel.
- Déclencheur : POST `/companies`, puis actions admin sur `/validations`.
- Nominal : création entreprise `pending` + demande de validation `pending` + notification admins → admin liste (autorisé) → approve (autorisé) : statut entreprise `active`, demande `approved`, notification demandeur.
- Alternative : admin reject (autorisé) : motif fourni, demande `rejected`, entreprise `rejected`, notification demandeur.
- Alternatives : accès validations refusé / approve/reject refusé → 403.
- Postconditions : une entreprise manuelle n’est activée qu’après approbation ; rejet laisse une trace motivée.

## 8. UC-AUDIT-01 — Journal d’actions consultable
    

```plantuml
@startuml
title UC-AUDIT-01 — Audit : consulter journal d'actions
actor Admin as ADM
participant "Web" as WEB
participant "AuditController" as AUD
participant "Policy(Audit)" as POL
database "DB" as DB

ADM -> WEB : GET /audit?filters&page=n
WEB -> AUD : index(filters,page)
AUD -> POL : authorize(viewAny)
alt ok
  AUD -> DB : SELECT audit_logs ORDER BY created_at desc LIMIT/OFFSET
  WEB --> ADM : liste
else ko
  WEB --> ADM : 403
end

ADM -> WEB : GET /audit/{id}
WEB -> AUD : show(id)
AUD -> POL : authorize(view, audit_log)
alt ok
  AUD -> DB : SELECT audit_log + payload(before/after)
  WEB --> ADM : détail
else ko
  WEB --> ADM : 403
end
@enduml
```

Scénario textuel (UC-AUDIT-01)

- Préconditions : écritures d’audit existantes ; rôle admin.
- Déclencheur : GET `/audit` puis GET `/audit/{id}`.
- Nominal : `viewAny` autorise la liste paginée → lecture DB → affichage liste → `view` autorise le détail → lecture DB → affichage détail.
- Alternatives : `viewAny` refuse → 403 ; `view` refuse → 403.
- Postconditions : consultation possible uniquement via autorisations ; la liste est paginée (risque DoS réduit).