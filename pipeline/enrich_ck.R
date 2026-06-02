# R enrich script — mirrors pipeline/enrich_buylist.py (API-first scryfall_id).
source(file.path(getwd(), "pipeline", "config.R"))

library(readr)
library(dplyr)
library(stringr)

aliases <- if (file.exists(file.path(helper_dir, "ck_set_aliases.csv"))) {
  read_csv(file.path(helper_dir, "ck_set_aliases.csv"), show_col_types = FALSE) %>%
    filter(!is.na(scryfall_set_name), scryfall_set_name != "")
} else {
  tibble(ck_name = character(), scryfall_set_name = character())
}

sets_lookup <- read_csv(scryfall_set_lookup, show_col_types = FALSE)
scryfall_cards <- read_csv(scryfall_cards_lookup, show_col_types = FALSE) %>%
  mutate(
    scryfall_id = as.character(scryfall_id),
    set_code = tolower(set_code),
    collector_number = as.character(collector_number)
  )

master_files <- list.files(
  buylist_master_dir,
  pattern = "^cardkingdom_buylist_master_",
  full.names = TRUE
)
if (length(master_files) == 0) stop("No master buylist file found.")
latest <- master_files[which.max(file.info(master_files)$mtime)]

ck <- read_csv(latest, show_col_types = FALSE)

if ("scryfall_id_api" %in% names(ck)) {
  ck <- ck %>%
    mutate(
      scryfall_id = coalesce(
        if ("scryfall_id" %in% names(.)) as.character(scryfall_id) else NA_character_,
        as.character(scryfall_id_api)
      )
    ) %>%
    select(-scryfall_id_api)
}

ck <- ck %>%
  mutate(
    finish = case_when(
      str_detect(name, regex("Foil Etched", ignore_case = TRUE)) ~ "etched",
      str_detect(set, regex("\\bFOIL\\b", ignore_case = TRUE)) ~ "foil",
      TRUE ~ "normal"
    ),
    clean_set = set,
    clean_set = str_replace_all(clean_set, "[\r\n]+", " "),
    clean_set = str_replace(clean_set, regex("\\s+FOIL$", ignore_case = TRUE), ""),
    clean_set = str_replace(clean_set, " FOIL$", ""),
    clean_set = str_replace(clean_set, " \\([A-Z]+\\)$", ""),
    clean_set = str_replace(clean_set, " JPN Planeswalkers$", ""),
    clean_set = str_replace(clean_set, " Variants$", ""),
    clean_set = str_replace(clean_set, " Commander Decks$", " Commander"),
    clean_set = str_replace(clean_set, "^Mystery Booster/The List$", "The List"),
    clean_set = str_replace(clean_set, regex("^Universes Beyond:\\s*", ignore_case = TRUE), ""),
    clean_set = if_else(clean_set == "Warhammer 40,000", "Warhammer 40,000 Commander", clean_set),
    clean_set = str_trim(clean_set)
  ) %>%
  left_join(aliases, by = c("clean_set" = "ck_name")) %>%
  mutate(
    scryfall_set_name = coalesce(scryfall_set_name, clean_set)
  ) %>%
  left_join(
    sets_lookup %>% transmute(scryfall_set_name = name, set_code = tolower(code)),
    by = "scryfall_set_name"
  )

cards_by_id <- scryfall_cards %>%
  select(scryfall_id, set_code, tcgplayer_id, tcgplayer_etched_id, usd, usd_foil, usd_etched) %>%
  distinct(scryfall_id, .keep_all = TRUE) %>%
  rename(
    set_code_sf = set_code,
    tcgplayer_id_sf = tcgplayer_id,
    tcgplayer_etched_id_sf = tcgplayer_etched_id,
    usd_sf = usd,
    usd_foil_sf = usd_foil,
    usd_etched_sf = usd_etched
  )

ck <- ck %>%
  left_join(cards_by_id, by = "scryfall_id") %>%
  mutate(
    set_code = coalesce(set_code, set_code_sf),
    tcgplayer_id = tcgplayer_id_sf,
    tcgplayer_etched_id = tcgplayer_etched_id_sf,
    usd = usd_sf,
    usd_foil = usd_foil_sf,
    usd_etched = usd_etched_sf
  ) %>%
  select(-ends_with("_sf"))

dir.create(buylist_enriched_dir, recursive = TRUE, showWarnings = FALSE)
out <- file.path(buylist_enriched_dir, paste0("full_ck_buylist_export_", Sys.Date(), ".csv"))
ck$snapshot_date <- as.character(Sys.Date())
write_csv(ck, out)
message("Wrote enriched buylist to ", out)
