
#include "common/types.hpp"

namespace
{
std::string extract_action_from_json(std::string_view json)
{
    const auto key_pos = json.find("\"action\"");
    if (key_pos == std::string_view::npos) {
        return {};
    }
    const auto colon_pos = json.find(':', key_pos);
    if (colon_pos == std::string_view::npos) {
        return {};
    }
    const auto first_quote = json.find('"', colon_pos + 1);
    if (first_quote == std::string_view::npos) {
        return {};
    }
    const auto second_quote = json.find('"', first_quote + 1);
    if (second_quote == std::string_view::npos || second_quote <= first_quote + 1) {
        return {};
    }
    return std::string(json.substr(first_quote + 1, second_quote - first_quote - 1));
}
}  // namespace

std::optional<Channel> Parser::parse_channel(std::string_view channel) {
    if (channel == "books")  return Channel::BOOKS;
    if (channel == "books5") return Channel::BOOKS5;
    if (channel == "trades") return Channel::TRADES;
    return std::nullopt;
}

std::optional<DoubleType> Parser::parse_decimal(std::string_view sv) {
    try {
        return DoubleType(std::string(sv));
    } catch (...) {
        return std::nullopt;
    }
}

std::optional<std::uint32_t> Parser::parse_u32(std::string_view sv) {
    std::uint32_t out{};
    auto [ptr, ec] = std::from_chars(sv.data(), sv.data() + sv.size(), out);
    if (ec != std::errc{} || ptr != sv.data() + sv.size()) {
        return std::nullopt;
    }
    return out;
}

std::optional<std::uint64_t> Parser::parse_u64(std::string_view sv) {
    std::uint64_t out{};
    auto [ptr, ec] = std::from_chars(sv.data(), sv.data() + sv.size(), out);
    if (ec != std::errc{} || ptr != sv.data() + sv.size()) {
        return std::nullopt;
    }
    return out;
}

std::optional<std::uint64_t> Parser::parse_u64_field(simdjson::ondemand::object& obj, const char* key) {
    auto field = obj[key];

    auto as_u64 = field.get_uint64();
    if (!as_u64.error()) {
        return as_u64.value();
    }

    auto as_string = field.get_string();
    if (!as_string.error()) {
        return parse_u64(std::string_view(as_string.value()));
    }

    return std::nullopt;
}

std::optional<std::uint32_t> Parser::parse_u32_field(simdjson::ondemand::object& obj, const char* key) {
    auto field = obj[key];

    auto as_u64 = field.get_uint64();
    if (!as_u64.error()) {
        const auto value = as_u64.value();
        if (value <= static_cast<std::uint64_t>(std::numeric_limits<std::uint32_t>::max())) {
            return static_cast<std::uint32_t>(value);
        }
        return std::nullopt;
    }

    auto as_string = field.get_string();
    if (!as_string.error()) {
        return parse_u32(std::string_view(as_string.value()));
    }

    return std::nullopt;
}

std::optional<Book> Parser::parse_book_level(simdjson::ondemand::array arr) {
    Book out{};
    std::size_t idx = 0;

    for (auto item : arr) {
        auto sres = item.get_string();
        if (sres.error()) {
            return std::nullopt;
        }

        const std::string_view sv = sres.value();

        switch (idx) {
            case 0: {
                auto v = parse_decimal(sv);
                if (!v) return std::nullopt;
                out.price = *v;
                break;
            }
            case 1: {
                auto v = parse_decimal(sv);
                if (!v) return std::nullopt;
                out.quantity = *v;
                break;
            }
            case 2: {
                auto v = parse_u32(sv);
                if (!v) return std::nullopt;
                out.deprecated_value = *v;
                break;
            }
            case 3: {
                auto v = parse_u32(sv);
                if (!v) return std::nullopt;
                out.order_count = *v;
                break;
            }
            default:
                return std::nullopt;
        }

        ++idx;
    }

    if (idx != 4) {
        return std::nullopt;
    }

    return out;
}

std::optional<Trade> Parser::parse_trade_object(simdjson::ondemand::object obj) {
    Trade t{};

    {
        auto v = obj["instId"].get_string();
        if (v.error()) return std::nullopt;
        t.instrument_id = std::string(std::string_view(v.value()));
    }

    {
        auto v = obj["tradeId"].get_string();
        if (v.error()) return std::nullopt;
        t.exchange_trade_id = std::string(std::string_view(v.value()));
    }

    {
        auto v = obj["px"].get_string();
        if (v.error()) return std::nullopt;
        auto parsed = parse_decimal(std::string_view(v.value()));
        if (!parsed) return std::nullopt;
        t.price = *parsed;
    }

    {
        auto v = obj["sz"].get_string();
        if (v.error()) return std::nullopt;
        auto parsed = parse_decimal(std::string_view(v.value()));
        if (!parsed) return std::nullopt;
        t.size = *parsed;
    }

    {
        auto v = obj["side"].get_string();
        if (v.error()) return std::nullopt;
        t.side = std::string(std::string_view(v.value()));
    }

    {
        auto parsed = parse_u64_field(obj, "ts");
        if (!parsed) return std::nullopt;
        t.exchange_ts_ms = *parsed;
    }

    {
        auto parsed = parse_u32_field(obj, "count");
        if (parsed) {
            t.trade_count = *parsed;
        }
    }

    {
        auto parsed = parse_u64_field(obj, "seqId");
        if (parsed) {
            t.sequence_id = *parsed;
        }
    }

    t.exchange = "OKX";
    return t;
}

std::optional<Arg> Parser::parse_arg() {
    auto doc_result = _parser.iterate(_json);
    if (doc_result.error()) {
        return std::nullopt;
    }

    auto doc = std::move(doc_result.value());

    auto arg_val = doc["arg"];
    if (arg_val.error()) {
        return std::nullopt;
    }

    auto arg_obj_res = arg_val.get_object();
    if (arg_obj_res.error()) {
        return std::nullopt;
    }

    auto arg_obj = arg_obj_res.value();
    Arg out{};

    {
        auto channel_res = arg_obj["channel"].get_string();
        if (channel_res.error()) {
            return std::nullopt;
        }

        auto channel = parse_channel(std::string_view(channel_res.value()));
        if (!channel) {
            return std::nullopt;
        }
        out.channel = *channel;
    }

    {
        auto inst_res = arg_obj["instId"].get_string();
        if (inst_res.error()) {
            return std::nullopt;
        }
        out.instrument_id = std::string(std::string_view(inst_res.value()));
    }

    return out;
}

std::optional<Books> Parser::parse_books() {
    const auto action = extract_action_from_json(std::string_view(_json.data(), _json.size()));

    auto doc_result = _parser.iterate(_json);
    if (doc_result.error()) {
        return std::nullopt;
    }

    auto doc = std::move(doc_result.value());
    Books out{};
    out.action = action;

    {
        auto inst = doc["arg"]["instId"].get_string();
        if (!inst.error()) {
            out.instrument_id = std::string(std::string_view(inst.value()));
        }
    }

    auto data_res = doc["data"].get_array();
    if (data_res.error()) {
        return std::nullopt;
    }

    auto data = data_res.value();
    auto it = data.begin();
    if (it == data.end()) {
        return std::nullopt;
    }

    auto obj_res = (*it).get_object();
    if (obj_res.error()) {
        return std::nullopt;
    }

    auto obj = obj_res.value();

    {
        auto parsed = parse_u64_field(obj, "ts");
        if (!parsed) return std::nullopt;
        out.exchange_ts_ms = *parsed;
    }

    {
        auto parsed = parse_u64_field(obj, "seqId");
        if (parsed) {
            out.sequence_id = *parsed;
        }
    }

    {
        auto bids_res = obj["bids"].get_array();
        if (bids_res.error()) return std::nullopt;

        for (auto entry : bids_res.value()) {
            auto level_res = entry.get_array();
            if (level_res.error()) return std::nullopt;

            auto book = parse_book_level(level_res.value());
            if (!book) return std::nullopt;

            out.bids.push_back(*book);
        }
    }

    {
        auto asks_res = obj["asks"].get_array();
        if (asks_res.error()) return std::nullopt;

        for (auto entry : asks_res.value()) {
            auto level_res = entry.get_array();
            if (level_res.error()) return std::nullopt;

            auto book = parse_book_level(level_res.value());
            if (!book) return std::nullopt;

            out.asks.push_back(*book);
        }
    }

    return out;
}

std::optional<Books5> Parser::parse_books5() {
    const auto action = extract_action_from_json(std::string_view(_json.data(), _json.size()));

    auto doc_result = _parser.iterate(_json);
    if (doc_result.error()) {
        return std::nullopt;
    }

    auto doc = std::move(doc_result.value());
    Books5 out{};
    out.action = action;

    {
        auto inst = doc["arg"]["instId"].get_string();
        if (inst.error()) return std::nullopt;
        out.instrument_id = std::string(std::string_view(inst.value()));
    }

    auto data_res = doc["data"].get_array();
    if (data_res.error()) {
        return std::nullopt;
    }

    auto data = data_res.value();
    auto it = data.begin();
    if (it == data.end()) {
        return std::nullopt;
    }

    auto obj_res = (*it).get_object();
    if (obj_res.error()) {
        return std::nullopt;
    }

    auto obj = obj_res.value();

    {
        auto parsed = parse_u64_field(obj, "ts");
        if (!parsed) return std::nullopt;
        out.exchange_ts_ms = *parsed;
    }

    {
        auto parsed = parse_u64_field(obj, "seqId");
        if (!parsed) return std::nullopt;
        out.sequence_id = *parsed;
    }

    {
        auto bids_res = obj["bids"].get_array();
        if (bids_res.error()) return std::nullopt;

        std::size_t i = 0;
        for (auto entry : bids_res.value()) {
            if (i >= 5) return std::nullopt;

            auto level_res = entry.get_array();
            if (level_res.error()) return std::nullopt;

            auto book = parse_book_level(level_res.value());
            if (!book) return std::nullopt;

            out.bids[i++] = *book;
        }

        if (i != 5) return std::nullopt;
    }

    {
        auto asks_res = obj["asks"].get_array();
        if (asks_res.error()) return std::nullopt;

        std::size_t i = 0;
        for (auto entry : asks_res.value()) {
            if (i >= 5) return std::nullopt;

            auto level_res = entry.get_array();
            if (level_res.error()) return std::nullopt;

            auto book = parse_book_level(level_res.value());
            if (!book) return std::nullopt;

            out.asks[i++] = *book;
        }

        if (i != 5) return std::nullopt;
    }

    return out;
}

std::optional<Trade> Parser::parse_trade() {
    auto doc_result = _parser.iterate(_json);
    if (doc_result.error()) {
        return std::nullopt;
    }

    auto doc = std::move(doc_result.value());
    auto obj_res = doc.get_object();
    if (obj_res.error()) {
        return std::nullopt;
    }

    return parse_trade_object(obj_res.value());
}

std::optional<Trades> Parser::parse_trades() {
    auto doc_result = _parser.iterate(_json);
    if (doc_result.error()) {
        return std::nullopt;
    }

    auto doc = std::move(doc_result.value());
    auto data_res = doc["data"].get_array();
    if (data_res.error()) {
        return std::nullopt;
    }

    Trades out{};

    for (auto item : data_res.value()) {
        auto obj_res = item.get_object();
        if (obj_res.error()) {
            return std::nullopt;
        }

        auto trade = parse_trade_object(obj_res.value());
        if (!trade) {
            return std::nullopt;
        }

        out.push_back(*trade);
    }

    return out;
}
