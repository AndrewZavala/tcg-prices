library(readr)
library(dplyr)
library(stringr)
library(lubridate)

# ---- paths ----
ck_folder <- "C:/Users/andre/Desktop/CK_buylist/master/Exports/CK Buylist Full"
tcg_cache_file <- "C:/Users/andre/Desktop/CK_buylist/master/Exports/TCGPlayer Data/TCGP_Master.csv"
output_folder <- "C:/Users/andre/Desktop/CK_buylist/master/Exports/TCG2CK"

dir.create(output_folder, recursive = TRUE, showWarnings = FALSE)

# ---- tuning ----
max_links_to_scrape <- 1000
min_cash_diff_est <- 0.50
max_cash_diff_est <- 100
min_buy_value_est <- 5
stale_days <- 0

# ---- latest CK Buylist Full export ----
ck_files <- list.files(
  path = ck_folder,
  pattern = "^full_ck_buylist_export_\\d{4}-\\d{2}-\\d{2}\\.csv$",
  full.names = TRUE
)

if (length(ck_files) == 0) {
  stop("No CK Buylist Full export files found.")
}

latest_ck_file <- ck_files %>%
  basename() %>%
  str_extract("\\d{4}-\\d{2}-\\d{2}") %>%
  as.Date() %>%
  order(decreasing = TRUE) %>%
  {\(idx) ck_files[idx[1]]}()

excluded_sets <- c(
  "Planechase",
  "Planechase 2012",
  "Planechase Anthology",
  "War of the Spark JPN Planeswalkers"
)

excluded_pattern <- str_c(excluded_sets, collapse = "|")

ck_cards <- read_csv(
  latest_ck_file,
  show_col_types = FALSE,
  col_types = cols(
    name = col_character(),
    set = col_character(),
    finish = col_character(),
    collector_number = col_character(),
    scryfall_id = col_character(),
    tcgplayer_id = col_double(),
    tcgplayer_etched_id = col_double(),
    cash_price = col_double(),
    credit_price = col_double(),
    max_qty = col_double(),
    set_code = col_character(),
    usd = col_double(),
    usd_foil = col_double(),
    usd_etched = col_double()
  )
) %>%
  mutate(
    tcg_price = case_when(
        finish == "foil" ~ usd_foil,
        finish == "etched" ~ usd_etched,
        TRUE ~ usd
        ),
    tcg_printing = case_when(
      finish == "foil" ~ "Foil",
      finish == "etched" ~ "Etched",
      TRUE ~ "Normal"
    ),
    cash_diff = cash_price - tcg_price,
    tcg_lookup_id = case_when(
      finish == "etched" ~ tcgplayer_etched_id,
      TRUE ~ tcgplayer_id
    ),
    roi = if_else(
      !is.na(tcg_price) & tcg_price > 0,
      (cash_price - tcg_price) / tcg_price,
      NA_real_
    ),
    tcg_url = if_else(
      !is.na(tcg_lookup_id),
      paste0(
        "https://www.tcgplayer.com/product/",
        tcg_lookup_id,
        "?page=1&Language=English&Printing=",
        tcg_printing
      ),
      NA_character_
    )
  )  %>%
  filter(
    !is.na(name),
    !str_detect(set, regex(excluded_pattern, ignore_case = TRUE))
    )

# ---- build scrape candidates directly from CK cards ----
links_to_scrape <- ck_cards %>%
  filter(
    !is.na(tcg_url),
    !is.na(tcg_lookup_id),
    !is.na(tcg_price),
    !is.na(cash_price),
    !is.na(cash_diff),
    !is.na(max_qty),
    max_qty > 0,
    tcg_price > 0,
    cash_price > 0,
    cash_diff >= min_cash_diff_est,
    cash_diff < max_cash_diff_est,
    (tcg_price * max_qty) >= min_buy_value_est
  ) %>%
  arrange(
    desc(cash_diff),
    desc(max_qty),
    desc(roi),
    name,
    set,
    finish
  ) %>%
  slice_head(n = max_links_to_scrape) %>%
  mutate(
    scrape_priority = row_number()
  )

# ---- write queue for scraper ----
scrape_queue <- links_to_scrape %>%
  select(
    scrape_priority,
    name,
    set,
    finish,
    scryfall_id,
    tcg_lookup_id,
    tcg_url,
    cash_price,
    credit_price,
    max_qty,
    tcg_price,
    cash_diff,
    roi
    ) %>%
  arrange(scrape_priority)

write_csv(
  scrape_queue,
  file.path(output_folder, paste0("tcg_scrape_queue_", Sys.Date(), ".csv"))
)

writeLines(
  scrape_queue$tcg_url,
  file.path(output_folder, paste0("tcg_scrape_queue_links_", Sys.Date(), ".txt"))
)

# ---- copy scrape links to clipboard ----
scrape_links <- scrape_queue %>%
  pull(tcg_url) %>%
  na.omit() %>%
  unique()

writeClipboard(scrape_links)

cat("Copied", length(scrape_links), "links to clipboard.\n")