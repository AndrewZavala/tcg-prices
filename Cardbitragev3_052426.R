library(readr)
library(dplyr)
library(stringr)
library(lubridate)

# ---- latest TCG scrape export ----
tcg_export_folder <- "C:/Users/andre/Desktop/CK_buylist/Buylist"
tcg_destination_folder <- "C:/Users/andre/Desktop/CK_buylist/master/Exports/TCGPlayer Data"

dir.create(tcg_destination_folder, recursive = TRUE, showWarnings = FALSE)

tcg_files <- list.files(
  path = tcg_export_folder,
  pattern = "^tcg_listings_export.*\\.csv$",
  full.names = TRUE
)

if (length(tcg_files) == 0) {
  stop("No tcg_listings_export CSV files found. Run the TCG scraper first.")
}

latest_tcg_file <- tcg_files[which.max(file.info(tcg_files)$mtime)]

# ---- read most recent TCG scrape export only ----
tcg_export <- read_csv(
  latest_tcg_file,
  show_col_types = FALSE,
  col_types = cols(
    tcg_lookup_id = col_double(),
    tcg_url = col_character(),
    source_page = col_double(),
    requested_printing = col_character(),
    seller = col_character(),
    card_name = col_character(),
    condition = col_character(),
    price = col_double(),
    shipping = col_double(),
    quantity_available = col_double(),
    total_each = col_double()
  )
)

cat("Using most recent TCG scrape file:\n", latest_tcg_file, "\n")
cat("TCG scrape rows:", nrow(tcg_export), "\n")

# ---- move used TCG scrape file out of Buylist folder ----
moved_tcg_file <- file.path(
  tcg_destination_folder,
  basename(latest_tcg_file)
)

move_success <- file.rename(
  from = latest_tcg_file,
  to = moved_tcg_file
)

if (!move_success) {
  stop("Failed to move TCG scrape file from Buylist to TCGPlayer Data folder.")
}

cat("Moved TCG scrape file to:\n", moved_tcg_file, "\n")

# ---- latest CK Buylist Full export ----
ck_folder <- "C:/Users/andre/Desktop/CK_buylist/master/Exports/CK Buylist Full"

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

ck_buylist <- read_csv(
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
    tcg_lookup_id = case_when(
      finish == "etched" ~ tcgplayer_etched_id,
      TRUE ~ tcgplayer_id
    ),
    tcg_printing = case_when(
      finish == "foil" ~ "Foil",
      finish == "etched" ~ "Etched",
      TRUE ~ "Normal"
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
    ),
    export_set = str_replace(set, " FOIL$", ""),
    export_set = str_replace(export_set, " \\([A-Z]+\\)$", ""),
    export_set = str_squish(export_set)
  )


# ---- keep only usable TCG rows ----
tcg_filtered <- tcg_export %>%
  filter(
    !is.na(tcg_lookup_id),
    !is.na(tcg_url),
    !is.na(total_each),
    !is.na(quantity_available),
    quantity_available > 0
  ) %>%
  mutate(
    requested_printing = case_when(
      requested_printing %in% c("Foil", "foil") ~ "foil",
      requested_printing %in% c("Etched", "etched") ~ "etched",
      TRUE ~ "normal"
    ),
    condition_lower = str_to_lower(condition)
  ) %>%
  filter(
    (requested_printing == "foil" & str_detect(condition_lower, "foil")) |
      (requested_printing == "etched" & str_detect(condition_lower, "etched")) |
      (requested_printing == "normal" &
         !str_detect(condition_lower, "foil") &
         !str_detect(condition_lower, "etched"))
  )

# ---- best single seller: highest quantity, then cheapest total_each ----
tcg_best_seller <- tcg_filtered %>%
  group_by(tcg_url, condition) %>%
  arrange(desc(quantity_available), price, .by_group = TRUE) %>%
  summarise(
    tcg_lookup_id = first(tcg_lookup_id),
    tcg_card_name = first(card_name),
    best_condition = first(condition),
    best_seller = first(seller),
    best_price = first(price),
    best_shipping = first(shipping),
    best_price = first(price),
    best_qty_available = first(quantity_available),
    tcg_total_quantity_by_condition = sum(quantity_available, na.rm = TRUE),
    tcg_listing_count_by_condition = n(),
    .groups = "drop"
  )

# ---- top 3 sellers by quantity ----
tcg_top3_summary <- tcg_filtered %>%
  group_by(tcg_url, condition) %>%
  arrange(desc(quantity_available), price, .by_group = TRUE) %>%
  slice_head(n = 3) %>%
  summarise(
    best_qty_top3 = sum(quantity_available, na.rm = TRUE),
    top3_total_cost = sum(quantity_available * price, na.rm = TRUE),
    avg_cost_top3 = if_else(
      best_qty_top3 > 0,
      top3_total_cost / best_qty_top3,
      NA_real_
    ),
    .groups = "drop"
  )

# ---- join to CK buylist and calculate metrics ----
ck_joined_best_seller <- ck_buylist %>%
  left_join(
    tcg_best_seller,
    by = "tcg_url"
  ) %>%
  left_join(
    tcg_top3_summary,
    by = c("tcg_url", "best_condition" = "condition")
  ) %>%
  mutate(
    condition_multiplier = case_when(
      best_condition %in% c("Near Mint", "Near Mint Foil") ~ 1.00,
      best_condition %in% c("Lightly Played", "Lightly Played Foil") ~ 0.75,
      best_condition %in% c("Moderately Played", "Moderately Played Foil") ~ 0.50,
      best_condition %in% c("Heavily Played", "Heavily Played Foil") ~ 0.25,
      TRUE ~ NA_real_
    ),
    adjusted_cash_price = cash_price * condition_multiplier,
    adjusted_credit_price = credit_price * condition_multiplier,
    
    fill_qty = pmin(best_qty_available, max_qty, na.rm = TRUE),
    cash_diff = adjusted_cash_price - best_price,
    credit_diff = adjusted_credit_price - best_price,
    roi = if_else(
      !is.na(best_price) & best_price > 0,
      (cash_diff / best_price) * 100,
      NA_real_
    ),
    profit_cash = fill_qty * cash_diff,
    profit_credit = fill_qty * credit_diff,
    
    fill_qty_top3 = pmin(best_qty_top3, max_qty, na.rm = TRUE),
    cash_diff_top3 = adjusted_cash_price - avg_cost_top3,
    profit_top3 = fill_qty_top3 * cash_diff_top3,
    
    buy_value_clean = fill_qty * best_price,
    buy_value_top3 = fill_qty_top3 * avg_cost_top3
  ) %>%
  filter(
    !is.na(best_price),
    !is.na(condition_multiplier),
    best_price > 0,
    cash_diff > 0,
    buy_value_clean >= 5
  ) %>%
  arrange(
    desc(profit_cash),
    desc(fill_qty),
    desc(roi),
    name,
    export_set,
    finish,
    best_condition
  )

# ---- write raw joined output ----
top200_dir <- "C:/Users/andre/Desktop/CK_buylist/master/Exports/Opp Finder/Top 200 TCGP"
dir.create(top200_dir, recursive = TRUE, showWarnings = FALSE)

write_csv(
  ck_joined_best_seller,
  file.path(
    top200_dir,
    paste0("tcg_best_seller_join_", Sys.Date(), ".csv")
  )
)

library(htmltools)

# ---- display table data ----
display_data <- ck_joined_best_seller %>%
  filter(
    !is.na(profit_cash),
    is.finite(profit_cash),
    profit_cash > 0
  ) %>%
  transmute(
    name = name,
    profit_cash_num = round(profit_cash, 2),
    cash_price_num = round(adjusted_cash_price, 2),
    max_qty = as.integer(max_qty),
    best_price_num = round(best_price, 2),
    best_qty_available = as.integer(best_qty_available),
    roi = round(roi, 1),
    best_qty_top3 = as.integer(best_qty_top3),
    profit_top3_num = round(profit_top3, 2),
    export_set,
    condition = best_condition,
    finish,
    tcg_url
  ) %>%
  mutate(
    profit_cash = paste0("$", format(profit_cash_num, nsmall = 2)),
    cash_price = paste0("$", format(cash_price_num, nsmall = 2)),
    best_price = paste0("$", format(best_price_num, nsmall = 2)),
    profit_top3 = paste0("$", format(profit_top3_num, nsmall = 2))
  ) %>%
  arrange(
    desc(profit_cash_num),
    desc(roi),
    desc(max_qty),
    name,
    export_set,
    finish
  )

cardbitrage_files_dir <- "C:/Users/andre/Desktop/CK_buylist/master/Exports/Opp Finder/Cardbitrage Files"
dir.create(cardbitrage_files_dir, recursive = TRUE, showWarnings = FALSE)

write.csv(
  display_data,
  file.path(cardbitrage_files_dir, paste0("hits_", Sys.Date(), ".csv")),
  row.names = FALSE
)

# ---- chart data ----
max_profit_cash <- max(display_data$profit_cash_num, na.rm = TRUE)

chart_data <- display_data %>%
  slice_head(n = 40) %>%
  mutate(
    profit_bar_pct = if (is.finite(max_profit_cash) && max_profit_cash > 0) {
      100 * profit_cash_num / max_profit_cash
    } else {
      0
    },
    roi_bar_pct = pmin(pmax(roi, 0), 100)
  )

# ---- chart rows ----
chart_rows <- lapply(seq_len(nrow(chart_data)), function(i) {
  tags$div(
    class = "chart-row",
    tags$div(class = "chart-label", chart_data$name[i]),
    tags$div(
      class = "chart-bar-wrap",
      tags$div(
        class = "profit-bar",
        style = paste0("width:", round(chart_data$profit_bar_pct[i], 1), "%;"),
        tags$div(
          class = "roi-bar",
          style = paste0("width:", round(chart_data$roi_bar_pct[i], 1), "%;")
        ),
        tags$span(
          class = "bar-text",
          paste0(
            chart_data$profit_cash[i],
            " | ROI ", format(chart_data$roi[i], nsmall = 1), "%"
          )
        )
      )
    )
  )
})

# ---- table rows ----
table_rows <- lapply(seq_len(nrow(display_data)), function(i) {
  tags$tr(
    tags$td(display_data$name[i]),
    tags$td(display_data$profit_cash[i]),
    tags$td(display_data$cash_price[i]),
    tags$td(display_data$max_qty[i]),
    tags$td(display_data$best_price[i]),
    tags$td(display_data$best_qty_available[i]),
    tags$td(display_data$roi[i]),
    tags$td(display_data$best_qty_top3[i]),
    tags$td(display_data$profit_top3[i]),
    tags$td(display_data$export_set[i]),
    tags$td(display_data$condition[i]),
    tags$td(display_data$finish[i]),
    tags$td(
      if (!is.na(display_data$tcg_url[i]) && display_data$tcg_url[i] != "") {
        tags$a(
          href = display_data$tcg_url[i],
          target = "_blank",
          "Open"
        )
      }
    )
  )
})

# ---- html page ----
html_page <- tagList(
  tags$head(
    tags$title("Cardbitrage"),
    tags$style(HTML("
      body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
        margin: 30px;
        background: #f5f7fa;
        color: #222;
      }
      h1, h2 {
        margin-bottom: 12px;
      }
      .subnote {
        margin-bottom: 18px;
        color: #555;
        font-size: 14px;
      }
      .chart-block, .table-block {
        background: white;
        border-radius: 12px;
        box-shadow: 0 3px 10px rgba(0,0,0,0.08);
        padding: 18px;
        margin-bottom: 24px;
      }
      .chart-row {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 10px;
      }
      .chart-label {
        width: 260px;
        min-width: 260px;
        font-size: 13px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .chart-bar-wrap {
        flex: 1;
        background: #e9eef5;
        border-radius: 999px;
        height: 28px;
        position: relative;
        overflow: hidden;
      }
      .profit-bar {
        height: 100%;
        background: linear-gradient(90deg, #2c7be5, #59a5ff);
        border-radius: 999px;
        position: relative;
        min-width: 2px;
      }
      .roi-bar {
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        height: 10px;
        background: rgba(255,255,255,0.85);
        border-radius: 999px;
      }
      .bar-text {
        position: absolute;
        right: 10px;
        top: 50%;
        transform: translateY(-50%);
        font-size: 12px;
        font-weight: 600;
        color: #0f172a;
      }
      input {
        width: 320px;
        padding: 8px 10px;
        margin-bottom: 14px;
        font-size: 14px;
      }
      table {
        border-collapse: collapse;
        width: 100%;
        background: white;
      }
      th {
        background: #1f2937;
        color: white;
        text-align: left;
        padding: 10px;
        font-size: 14px;
        position: sticky;
        top: 0;
      }
      th.sortable {
        cursor: pointer;
        position: relative;
        padding-right: 22px;
      }
      th.sortable::after {
        content: '↕';
        position: absolute;
        right: 8px;
        color: #cbd5e1;
        font-size: 12px;
      }
      th.sortable.sort-asc::after {
        content: '▲';
        color: #ffffff;
      }
      th.sortable.sort-desc::after {
        content: '▼';
        color: #ffffff;
      }
      th.sortable:hover {
        background: #374151;
      }
      td {
        padding: 9px 10px;
        border-bottom: 1px solid #eee;
        white-space: nowrap;
      }
      tr:hover {
        background: #f1f6ff;
      }
    "))
  ),
  tags$body(
    tags$h1("Cardbitrage"),
    tags$div(
      class = "subnote",
      "Profit bar length = profit_cash. White mini-bar inside = ROI %, capped at 100% width."
    ),
    
    tags$div(
      class = "chart-block",
      tags$h2("Top 40 by Profit Cash"),
      chart_rows
    ),
    
    tags$div(
      class = "table-block",
      tags$h2("Data Table"),
      tags$input(
        id = "searchBox",
        type = "text",
        placeholder = "Search card name..."
      ),
      tags$table(
        id = "dataTable",
        tags$thead(
          tags$tr(
            tags$th("name"),
            tags$th(`data-col` = "1", `data-type` = "num", class = "sortable", "profit_cash"),
            tags$th("cash_price"),
            tags$th(`data-col` = "3", `data-type` = "num", class = "sortable", "max_qty"),
            tags$th("best_price"),
            tags$th(`data-col` = "5", `data-type` = "num", class = "sortable", "best_qty_available"),
            tags$th(`data-col` = "6", `data-type` = "num", class = "sortable", "roi"),
            tags$th(`data-col` = "7", `data-type` = "num", class = "sortable", "best_qty_top3"),
            tags$th(`data-col` = "8", `data-type` = "num", class = "sortable", "profit_top3"),
            tags$th("export_set"),
            tags$th("condition"),
            tags$th("finish"),
            tags$th("tcg")
          )
        ),
        tags$tbody(table_rows)
      )
    ),
    
    tags$script(HTML("
      const searchBox = document.getElementById('searchBox');
      const table = document.getElementById('dataTable');
      const tbody = table.querySelector('tbody');
      const headers = table.querySelectorAll('th.sortable');

      searchBox.addEventListener('keyup', function() {
        const filter = this.value.toLowerCase();
        const rows = document.querySelectorAll('#dataTable tbody tr');

        rows.forEach(function(row) {
          const cardName = row.cells[0].innerText.toLowerCase();
          row.style.display = cardName.includes(filter) ? '' : 'none';
        });
      });

      headers.forEach(header => {
        header.dataset.sortDir = 'desc';

        header.addEventListener('click', function() {
          const colIndex = parseInt(this.dataset.col, 10);
          const type = this.dataset.type;
          const currentDir = this.dataset.sortDir;
          const newDir = currentDir === 'asc' ? 'desc' : 'asc';

          headers.forEach(h => {
            h.classList.remove('sort-asc', 'sort-desc');
          });

          this.dataset.sortDir = newDir;
          this.classList.add(newDir === 'asc' ? 'sort-asc' : 'sort-desc');

          const rows = Array.from(tbody.querySelectorAll('tr'));

          rows.sort((a, b) => {
            let aVal = a.cells[colIndex].innerText.trim();
            let bVal = b.cells[colIndex].innerText.trim();

            if (type === 'num') {
              aVal = parseFloat(aVal.replace(/[^0-9.-]/g, '')) || 0;
              bVal = parseFloat(bVal.replace(/[^0-9.-]/g, '')) || 0;
            } else {
              aVal = aVal.toLowerCase();
              bVal = bVal.toLowerCase();
            }

            if (aVal < bVal) return newDir === 'asc' ? -1 : 1;
            if (aVal > bVal) return newDir === 'asc' ? 1 : -1;
            return 0;
          });

          rows.forEach(row => tbody.appendChild(row));
        });
      });
    "))
  )
)

# ---- save html ----
output_dir <- "C:/Users/andre/Desktop/CK_buylist/master/Exports/Opp Finder/Cardbitrage HTML"
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

html_file <- file.path(
  output_dir,
  paste0("Cardbitrage_", Sys.Date(), ".html")
)

save_html(
  html_page,
  html_file
)

browseURL(html_file)

# ---- due diligence check: remove joined best seller hits from latest CK cards file ----
remaining_ck_cards <- ck_buylist %>%
  anti_join(
    ck_joined_best_seller %>%
      filter(!is.na(tcg_url)) %>%
      distinct(tcg_url),
    by = "tcg_url"
  ) %>%
  select(
    name,
    set,
    export_set,
    finish,
    collector_number,
    scryfall_id,
    tcgplayer_id,
    tcgplayer_etched_id,
    tcg_lookup_id,
    tcg_url,
    cash_price,
    credit_price,
    max_qty,
    tcg_price,
    set_code
  )

write_csv(
  remaining_ck_cards,
  file.path(
    "C:/Users/andre/Desktop/CK_buylist/master/Exports/Opp Finder/",
    paste0("ck_cards_remaining_after_cardbitrage_", Sys.Date(), ".csv")
  )
)

cat("Read CK file:\n", latest_ck_file, "\n")
cat("Read TCG master file:\n", tcg_master_file, "\n")
cat("Cardbitrage hits:", nrow(display_data), "\n")
cat("Remaining CK cards:", nrow(remaining_ck_cards), "\n")