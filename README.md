# huis-tracker

Overzicht van koopwoningen van woningcorporaties in Amsterdam, met de voorrangsregels voor sociale huurders.

- `index.html` – de website (lijst, filters, kaart met PDOK-achtergrondkaart, licht/donker).
- `data/woningen.json` – alle woningen; `data/regels.json` – voorrangsregels; `data/bronnen.json` – status per bron.
- `scraper/update.py` – haalt dagelijks het aanbod van de Alliantie en Lieven de Key op (GitHub Actions, `.github/workflows/update.yml`) en geocodeert nieuwe adressen via PDOK.

Stadgenoot- en Funda-woningen komen binnen via e-mailalerts en worden apart toegevoegd.
