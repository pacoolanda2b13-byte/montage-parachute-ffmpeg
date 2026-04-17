# 🌳 Arbre généalogique — SkyDive Pro

```
                                ┌──────────────────────┐
                                │   🪂 SKYDIVE PRO      │
                                │    v0.1.0-demo       │
                                │   (17/04/2026)       │
                                └──────────┬───────────┘
                                           │
        ┌──────────────────────────────────┼──────────────────────────────────┐
        │                                  │                                  │
   ┌────▼─────┐                      ┌─────▼──────┐                   ┌───────▼──────┐
   │ 🎯 VISION │                      │ 🏗️ ARCHI   │                   │ ✅ LIVRABLES │
   │  (idée)   │                      │ (structure) │                   │  (résultats) │
   └────┬─────┘                      └─────┬──────┘                   └───────┬──────┘
        │                                  │                                  │
        ├─ Dropzone tandem 10-30 sauts/j   ├─ core/  (moteurs IA)            ├─ 🟢 README.md
        ├─ Vidéo 15min → montage 3-4min    ├─ agent/ (orchestrateur)         ├─ 🟢 PLAN_EXECUTION.md
        ├─ 9 scènes IA                     ├─ api/   (Flask + routes)        ├─ 🟢 Dashboard HTML
        ├─ Livraison auto mail             ├─ ui/    (dashboard)             ├─ 🟢 Tests fixtures
        └─ Stratégie hybride gratuite      ├─ assets/ (logo, musique, LUT)   ├─ 🟢 Pipeline bout-en-bout
                                           ├─ db/    (SQLite migrations)     └─ 🟢 Montage démo
                                           ├─ tests/ (fixtures + unit)          prod: 76 MB / 1:29
                                           └─ config/ (yaml + .env)

  ══════════════════════════════════════════════════════════════════════════════════

                          ┌────────────────────────────┐
                          │  🛠️  JALONS DE DÉVELOPPEMENT  │
                          └──────────────┬─────────────┘
                                         │
   ┌──────────────┬──────────────┬──────┼────────┬──────────────┬──────────────┐
   │              │              │      │        │              │              │
 ┌─▼────┐     ┌───▼────┐    ┌────▼──┐ ┌─▼──┐  ┌──▼────┐    ┌────▼────┐   ┌─────▼────┐
 │  J0  │     │   J1   │    │  J2   │ │ J3 │  │  J4   │    │   J5    │   │   J6-7   │
 │Setup │     │Télémét.│    │Scènes │ │Over│  │ FFmpeg │    │Dashboard│   │Delivery  │
 │✅ 100%│     │✅ 100% │    │✅ 100%│ │✅100│  │✅ 100% │    │🟡 30%   │   │⏳ 0%     │
 └──┬───┘     └───┬────┘    └──┬────┘ └──┬─┘  └───┬────┘    └────┬────┘   └────┬─────┘
    │             │            │         │        │              │             │
    │             │            │         │        │              │             │
 • venv         • GPMF       • Audio  • Intro  • Cut clips   • Sidebar      • Gmail API
 • FFmpeg       • GPS5         librosa  PNG     • Concat      • Stats cards  • Drive API
 • Config       • ACCL       • Gemini • Outro  • Mix music   • Jobs list    • SMS/QR
 • Dépend.      • SCAL         Vision   PNG    • LUT color   • Upload fich. • Scheduler
 • Logger       • Phases     • Fusion • Stats  • Encoder GPU • Onglets URL  • Monitoring
                              télémé. + vision          AMF/NVENC
                              + audio
                              + vision
 ✓ Python      ✓ 3 vidéos   ✓ 17 seg ✓ Logo  ✓ AMD AMF      ✓ Modal         × TODO
 ✓ 3.14 OK      officielles    sur YT  dyn     hardware      new jump        × DeepFace
 ✓ venv         GoPro          test    ✓ Nom   ✓ Concat      ✓ Upload fich   × Interact
 ✓ Gemini      ✓ 618 GPS              ✓ Date   ✓ Apostr      ✓ URL import    × N8N
 ✓ MediaPipe   ✓ 6870 ACCL            ✓ Stats   safe
 ✓ OpenCV      ✓ Carlsbad CA         ✓ HUD
                validé                 3 cards

  ══════════════════════════════════════════════════════════════════════════════════

                       ┌───────────────────────────────┐
                       │  📊 7 COMMITS GITHUB (chrono)  │
                       └──────────────┬────────────────┘
                                      │
     833e2d3  ◄─ init SkyDive Pro v2
        │
     ae082db  ◄─ Dashboard v2 + form + J1 telemetry
        │
     89f4b90  ◄─ J1.5 GPMF complete parser (validé 3 samples)
        │
     d39c949  ◄─ J2+J3+J4 pipeline bout-en-bout
        │
     0ad7b22  ◄─ 15 fixes P0/P1 du dual code review
        │
     08ae493  ◄─ URL importer universel (YouTube/WT/Drive/...)
        │
     c781959  ◄─ Gemini rate-limit shortcircuit + model update
        │
   🏷️ v0.1.0-demo ◄─ TAG : prêt pour test client

  ══════════════════════════════════════════════════════════════════════════════════

                       ┌───────────────────────────────┐
                       │  📦 STACK TECHNIQUE UTILISÉE  │
                       └──────────────┬────────────────┘
                                      │
         ┌─────────────┬───────────────┼──────────────┬──────────────┐
         │             │               │              │              │
      ┌──▼──┐     ┌────▼────┐    ┌─────▼────┐    ┌────▼─────┐    ┌───▼────┐
      │Back │     │  Vidéo  │    │    IA    │    │  Front   │    │ Infra  │
      │-end │     │         │    │          │    │          │    │        │
      └─┬───┘     └────┬────┘    └─────┬────┘    └────┬─────┘    └───┬────┘
        │              │               │              │              │
     • Python      • FFmpeg 7.x    • Gemini 3-flash  • HTML5       • Git/GitHub
        3.14       • h264_amf      • MediaPipe       • CSS3         (feat/skydive
     • Flask 3.x    (AMD GPU)      • OpenCV          • JS vanilla    -pro-v2)
     • SQLAlchemy  • MoviePy       • scenedetect     • Responsive  • venv isolé
     • Pydantic    • librosa                          design       • Launch.json
     • python-     • Pillow                          • Modal +     • Preview
        dotenv     • gopro-GPMF                       drag&drop      server
     • threading    parser                                           port 5000
     • logging                                                      • Tests
                                                                     fixtures

  ══════════════════════════════════════════════════════════════════════════════════

                       ┌───────────────────────────────┐
                       │    🧪 TESTS RÉALISÉS          │
                       └──────────────┬────────────────┘
                                      │
                ┌─────────────────────┼─────────────────────┐
                │                     │                     │
          ┌─────▼──────┐      ┌───────▼───────┐     ┌──────▼──────┐
          │  Unitaires │      │  Intégration  │     │  End-to-End │
          └─────┬──────┘      └───────┬───────┘     └──────┬──────┘
                │                     │                    │
           ✓ select_best_clips   ✓ Télémétrie         ✓ hero5.mp4
             clamp >= 0            3 samples GoPro      → succès 9.6s
           ✓ phases_from_vision  ✓ Scene detection    ✓ YouTube 12min
             filtre erreur         audio seul           → succès 11.1s
           ✓ Tous modules        ✓ Pipeline            → 4 scènes
             chargent              orchestrateur      ✓ YouTube + Gemini
                                                         → succès 298s
                                                         → 17 scènes
                                                         → 76 MB montage

  ══════════════════════════════════════════════════════════════════════════════════

                       ┌───────────────────────────────┐
                       │    ⏳ PROCHAINES ÉTAPES        │
                       └──────────────┬────────────────┘
                                      │
         ┌────────────┬───────────────┼───────────────┬────────────┐
         │            │               │               │            │
      ┌──▼───┐   ┌────▼─────┐    ┌────▼────┐    ┌─────▼────┐   ┌───▼──────┐
      │CE SOIR│  │  S+1     │    │   S+2   │    │   S+3    │   │   S+4    │
      │ Test  │  │ Délivery │    │Émotions │    │Dashboard │   │ Deploy   │
      │ client│  │  (J6)    │    │  DeepF. │    │ complet  │   │  prod    │
      │       │  │          │    │  (J2b)  │    │  (J5)    │   │  (J7)    │
      └──┬────┘  └────┬─────┘    └────┬────┘    └─────┬────┘   └───┬──────┘
         │            │               │                │           │
      • Upload     • Gmail auto     • Face detect  • SQLite DB    • Service
        vidéo      • Drive upload    reactions     • Historique    Windows
      • Pipeline   • Email template  au sol        • Preview GIF   Task Schd
      • Download   • QR code         moniteur      • Stats réelles• Backup
        résultat   • Twilio SMS      passager      • Auth staff    quotidien
      • Feedback                                                   • SSL cert
      client

  ══════════════════════════════════════════════════════════════════════════════════

                       ┌───────────────────────────────┐
                       │    💰 MÉTRIQUES PROJET         │
                       └──────────────┬────────────────┘
                                      │
      ┌───────────────────┬───────────┴────────────┬───────────────────────┐
      │                   │                        │                       │
  Lignes code        Temps dev             Coûts réalisés          Coûts prod
  ───────────        ─────────             ──────────────          ──────────
  • ~3500 Python     • 1 session           • 0 € API Gemini        • ~5-15 €/mois
  • ~600 HTML/CSS    • 8 jalons           • 0 € libs (open        • ~15 €/mois
  • ~500 config/yml    complétés            source)                 Google Workspace
                                          • 0 € hosting           • ~15-30 €/mois
                                            (local)                 musique Epidemic
                                                                 = ~35-60 €/mois

                           Potentiel CA : 250-350 € × tandem
                           Break-even : dès 1 tandem/mois
```

---

## 📊 Vue synthétique par statut

| Catégorie | Terminé | En cours | À faire |
|---|---|---|---|
| Jalons techniques | J0, J1, J1.5, J2, J3, J4 | J5 (30%) | J2b, J2c, J6, J7 |
| Intégrations | Télémétrie, Gemini, FFmpeg | — | Gmail, Drive, SMS |
| Docs | README, PLAN, ARBRE | — | Client onboarding |
| Tests | 3 sessions validées | — | Test client ce soir |

**Position dans le cycle de dev : 60% terminé**, le reste = livraison automatique + polish production.
