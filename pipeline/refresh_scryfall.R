source(file.path(getwd(), "pipeline", "config.R"))

library(jsonlite)
library(dplyr)
library(readr)

dir.create(helper_dir, recursive = TRUE, showWarnings = FALSE)

bulk_meta <- fromJSON("https://api.scryfall.com/bulk-data")
default_cards_uri <- bulk_meta$data$download_uri[bulk_meta$data$type == "default_cards"]

bulk_json <- file.path(helper_dir, "scryfall_default_cards.json")
download.file(default_cards_uri, destfile = bulk_json, mode = "wb", quiet = TRUE)

scryfall_raw <- fromJSON(bulk_json, flatten = TRUE)

scryfall_cards <- scryfall_raw %>%
  transmute(
    scryfall_id = id,
    set_code = tolower(set),
    collector_number = as.character(collector_number),
    tcgplayer_id = tcgplayer_id,
    tcgplayer_etched_id = tcgplayer_etched_id,
    usd = prices.usd,
    usd_foil = prices.usd_foil,
    usd_etched = prices.usd_etched
  )

write_csv(scryfall_cards, scryfall_cards_lookup)
message("Wrote ", nrow(scryfall_cards), " rows to ", scryfall_cards_lookup)
