source(file.path(getwd(), "pipeline", "config.R"))

library(readr)
library(dplyr)
library(stringr)
library(purrr)

raw_today <- file.path(buylist_raw_dir, format(Sys.Date(), "%Y-%m-%d"))
folders <- c(raw_today, buylist_legacy_dir)
folders <- folders[dir.exists(folders)]

files <- unlist(lapply(folders, function(d) {
  list.files(d, pattern = "\\.csv$", full.names = TRUE)
}))

if (length(files) == 0) {
  stop("No buylist CSV files found in raw or legacy Buylist folder.")
}

ck_all <- map_dfr(files, function(f) {
  message("Reading: ", basename(f))
  read_csv(
    f,
    show_col_types = FALSE,
    quote = "\"",
    col_types = cols(collector_number = col_character())
  ) %>%
    mutate(source_file = basename(f))
})

ck_all <- ck_all %>%
  mutate(
    finish = str_squish(finish),
    rarity_bucket = str_squish(rarity_bucket),
    name = str_squish(name),
    set = str_replace_all(set, "\\r|\\n", " "),
    set = str_squish(set),
    type = str_replace_all(type, "\\r|\\n", " "),
    type = str_squish(type),
    collector_number = str_remove(collector_number, "^Collector #:\\s*"),
    collector_number = str_squish(collector_number),
    cash_price = parse_number(as.character(cash_price)),
    credit_price = parse_number(as.character(credit_price)),
    max_qty = suppressWarnings(as.integer(max_qty)),
    slug = str_squish(slug),
    product_id = as.character(product_id)
  )

ck_all_deduped <- ck_all %>% distinct(product_id, .keep_all = TRUE)

dir.create(buylist_master_dir, recursive = TRUE, showWarnings = FALSE)
out <- file.path(
  buylist_master_dir,
  paste0("cardkingdom_buylist_master_", Sys.Date(), ".csv")
)
write_csv(ck_all_deduped, out)
message("Wrote ", nrow(ck_all_deduped), " rows to ", out)
