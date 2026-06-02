tcg_root <- Sys.getenv("TCG_ROOT", unset = "")
if (!nzchar(tcg_root)) {
  wd <- normalizePath(getwd(), winslash = "/")
  if (dir.exists(file.path(wd, "pipeline"))) {
    tcg_root <- wd
  } else if (dir.exists(file.path(wd, "..", "pipeline"))) {
    tcg_root <- normalizePath(file.path(wd, ".."), winslash = "/")
  } else {
    tcg_root <- wd
  }
}

tcg_path <- function(...) file.path(tcg_root, ...)

helper_dir <- tcg_path("helper")
buylist_raw_dir <- tcg_path("data", "buylist", "raw")
buylist_legacy_dir <- tcg_path("Buylist")
buylist_master_dir <- tcg_path("data", "buylist", "master")
buylist_enriched_dir <- tcg_path("data", "buylist", "enriched")

scryfall_set_lookup <- file.path(helper_dir, "scryfall_set_lookup.csv")
scryfall_cards_lookup <- file.path(helper_dir, "scryfall_cards_lookup.csv")
