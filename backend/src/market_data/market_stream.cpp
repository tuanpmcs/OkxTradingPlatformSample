#include "market_data/market_stream.hpp"

#include <cmath>
#include <sstream>
#include <stdexcept>

namespace
{
constexpr std::size_t kCsvFlushEveryRows = 256;

std::string decimal_to_string(const DoubleType& value)
{
    std::ostringstream oss;
    oss << value;
    return oss.str();
}

double decimal_to_double(const DoubleType& value)
{
    return value.convert_to<double>();
}

std::string to_fixed_string(double value, int precision = 10)
{
    std::ostringstream oss;
    oss.setf(std::ios::fixed);
    oss.precision(precision);
    oss << value;
    return oss.str();
}

std::string csv_escape(const std::string& input)
{
    bool needs_quotes = false;
    for (char c : input)
    {
        if (c == ',' || c == '"' || c == '\n' || c == '\r')
        {
            needs_quotes = true;
            break;
        }
    }
    if (!needs_quotes)
    {
        return input;
    }

    std::string out;
    out.reserve(input.size() + 4);
    out.push_back('"');
    for (char c : input)
    {
        if (c == '"')
        {
            out.push_back('"');
        }
        out.push_back(c);
    }
    out.push_back('"');
    return out;
}

void put_feature_fields(std::map<std::string, std::string>& fields, const FeatureSnapshot& feature)
{
    fields["mid_price"] = to_fixed_string(feature.mid_price);
    fields["spread"] = to_fixed_string(feature.spread);
    fields["imbalance"] = to_fixed_string(feature.imbalance);
    fields["trade_volume"] = to_fixed_string(feature.trade_volume);
    fields["trade_imbalance"] = to_fixed_string(feature.trade_imbalance);
}

std::optional<double> top_mid(const Book& bid, const Book& ask)
{
    const auto bid_px = decimal_to_double(bid.price);
    const auto ask_px = decimal_to_double(ask.price);
    if (bid_px > 0.0 && ask_px > bid_px)
    {
        return 0.5 * (bid_px + ask_px);
    }
    return std::nullopt;
}

}  // namespace

MarketEventDispatcher::MarketEventDispatcher(MarketEventListener& listener)
    : _listener(listener)
{
}

bool MarketEventDispatcher::dispatch(const std::string& payload)
{
    Parser parser(payload);
    auto arg = parser.parse_arg();

    if (!arg)
    {
        return false;
    }

    if (arg->channel == Channel::TRADES)
    {
        const auto trades = parser.parse_trades();
        if (!trades || trades->empty())
        {
            return false;
        }
        _listener.on_trades(*trades, payload);
        return true;
    }
    else if (arg->channel == Channel::BOOKS5)
    {
        const auto books5 = parser.parse_books5();
        if (!books5)
        {
            return false;
        }
        _listener.on_books5(*books5, payload);
        return true;
    }
    else if (arg->channel == Channel::BOOKS)
    {
        const auto books = parser.parse_books();
        if (!books)
        {
            return false;
        }
        _listener.on_books(*books, payload);
        return true;
    }

    return false;
}

CsvTickWriter::CsvTickWriter(const std::string& path)
{
    _out.open(path, std::ios::out | std::ios::trunc);
    if (!_out.is_open())
    {
        throw std::runtime_error("Failed to open csv output: " + path);
    }
    write_header();
}

void CsvTickWriter::write(const StreamRecord& tick)
{
    const auto getv = [&](const char* key) -> std::string {
        const auto it = tick.fields.find(key);
        return (it == tick.fields.end()) ? "" : it->second;
    };

    _out << tick.ts_ms << ','
         << to_fixed_string(tick.price, 8) << ','
         << csv_escape(infer_event_type(getv("channel"))) << ','
         << csv_escape(getv("channel")) << ','
         << csv_escape(getv("instId")) << ','
         << csv_escape(getv("book_action")) << ','
         << csv_escape(getv("side")) << ','
         << csv_escape(getv("sz")) << ','
         << csv_escape(getv("bidPx")) << ','
         << csv_escape(getv("askPx")) << ','
         << csv_escape(getv("bidSz")) << ','
         << csv_escape(getv("askSz")) << ','
         << csv_escape(getv("spread")) << ','
         << csv_escape(getv("mid_price")) << ','
         << csv_escape(getv("mid_price")) << ','
         << csv_escape(getv("spread")) << ','
         << csv_escape(getv("imbalance")) << ','
         << csv_escape(getv("trade_volume")) << ','
         << csv_escape(getv("trade_imbalance")) << ','
         << csv_escape(tick.source) << '\n';
    ++_rows_since_flush;
    if ((_rows_since_flush % kCsvFlushEveryRows) == 0)
    {
        _out.flush();
    }
}

std::string CsvTickWriter::infer_event_type(const std::string& channel)
{
    return channel.find("trade") != std::string::npos ? "trade" : "order_book";
}

void CsvTickWriter::write_header()
{
    _out << "ts,price,event_type,channel,instId,book_action,trade_side,trade_size,bidPx,askPx,bidSz,askSz,"
            "spread,mid_price,mid_price_feat,spread_feat,imbalance_feat,trade_volume_feat,"
            "trade_imbalance_feat,source\n";
    _out.flush();
}

FeatureAccumulator::FeatureAccumulator(std::int64_t trade_window_ms)
    : _trade_window_ms(trade_window_ms)
{
}

void FeatureAccumulator::observe_books(const Books& books)
{
    auto& state = _books_by_inst[books.instrument_id];
    if (books.action == "snapshot" || (state.bids.empty() && state.asks.empty()))
    {
        state.bids.clear();
        state.asks.clear();
    }

    for (const auto& level : books.bids)
    {
        const auto px = decimal_to_double(level.price);
        const auto sz = decimal_to_double(level.quantity);
        if (!(px > 0.0))
        {
            continue;
        }
        if (sz <= 0.0)
        {
            state.bids.erase(px);
        }
        else
        {
            state.bids[px] = sz;
        }
    }

    for (const auto& level : books.asks)
    {
        const auto px = decimal_to_double(level.price);
        const auto sz = decimal_to_double(level.quantity);
        if (!(px > 0.0))
        {
            continue;
        }
        if (sz <= 0.0)
        {
            state.asks.erase(px);
        }
        else
        {
            state.asks[px] = sz;
        }
    }

    if (!state.bids.empty() && !state.asks.empty())
    {
        _bid_px = state.bids.begin()->first;
        _bid_sz = state.bids.begin()->second;
        _ask_px = state.asks.begin()->first;
        _ask_sz = state.asks.begin()->second;
    }
}

void FeatureAccumulator::observe_books5(const Books5& books5)
{
    _bid_px = decimal_to_double(books5.bids[0].price);
    _ask_px = decimal_to_double(books5.asks[0].price);
    _bid_sz = decimal_to_double(books5.bids[0].quantity);
    _ask_sz = decimal_to_double(books5.asks[0].quantity);
}

void FeatureAccumulator::observe_trade(const Trade& trade)
{
    const auto abs_size = decimal_to_double(trade.size);
    if (!(abs_size > 0.0))
    {
        return;
    }

    double sign = 0.0;
    if (trade.side == "buy")
    {
        sign = 1.0;
    }
    else if (trade.side == "sell")
    {
        sign = -1.0;
    }

    _trades.push_back({static_cast<std::int64_t>(trade.exchange_ts_ms), abs_size, sign * abs_size});
}

void FeatureAccumulator::prune(std::int64_t now_ms)
{
    const std::int64_t threshold = now_ms - _trade_window_ms;
    while (!_trades.empty() && _trades.front().ts_ms < threshold)
    {
        _trades.pop_front();
    }
}

FeatureSnapshot FeatureAccumulator::snapshot() const
{
    FeatureSnapshot out{};

    if (_bid_px.has_value() && _ask_px.has_value() && *_bid_px > 0.0 && *_ask_px > *_bid_px)
    {
        out.mid_price = 0.5 * (*_bid_px + *_ask_px);
        out.spread = *_ask_px - *_bid_px;
    }

    if (_bid_sz.has_value() && _ask_sz.has_value())
    {
        const auto denom = *_bid_sz + *_ask_sz;
        if (denom > 0.0)
        {
            out.imbalance = (*_bid_sz - *_ask_sz) / denom;
        }
    }

    for (const auto& trade : _trades)
    {
        out.trade_volume += trade.abs_size;
        out.trade_imbalance += trade.signed_size;
    }

    return out;
}

StreamRecord make_stream_record_from_books(const Books& books,
                                           const FeatureSnapshot& feature,
                                           std::optional<double> last_price,
                                           const std::string& raw_json,
                                           const std::string& channel)
{
    StreamRecord record;
    record.ts_ms = static_cast<std::int64_t>(books.exchange_ts_ms);
    record.source = "cxx-grpc";
    record.raw_json = raw_json;
    record.fields["channel"] = channel;
    record.fields["instId"] = books.instrument_id;
    record.fields["book_action"] = books.action;
    record.fields["ts"] = std::to_string(books.exchange_ts_ms);
    record.fields["seqId"] = std::to_string(books.sequence_id);

    if (!books.bids.empty() && !books.asks.empty())
    {
        record.fields["bidPx"] = decimal_to_string(books.bids.front().price);
        record.fields["bidSz"] = decimal_to_string(books.bids.front().quantity);
        record.fields["askPx"] = decimal_to_string(books.asks.front().price);
        record.fields["askSz"] = decimal_to_string(books.asks.front().quantity);
    }

    put_feature_fields(record.fields, feature);

    record.price = feature.mid_price;
    if (!(record.price > 0.0) && !books.bids.empty() && !books.asks.empty())
    {
        const auto fallback_mid = top_mid(books.bids.front(), books.asks.front());
        if (fallback_mid)
        {
            record.price = *fallback_mid;
        }
    }

    record.change = last_price.has_value() ? (record.price - *last_price) : 0.0;
    return record;
}

StreamRecord make_stream_record_from_trade(const Trade& trade,
                                           const FeatureSnapshot& feature,
                                           std::optional<double> last_price,
                                           const std::string& raw_json)
{
    StreamRecord record;
    record.ts_ms = static_cast<std::int64_t>(trade.exchange_ts_ms);
    record.price = decimal_to_double(trade.price);
    record.change = last_price.has_value() ? (record.price - *last_price) : 0.0;
    record.source = "cxx-grpc";
    record.raw_json = raw_json;

    record.fields["channel"] = "trades";
    record.fields["instId"] = trade.instrument_id;
    record.fields["ts"] = std::to_string(trade.exchange_ts_ms);
    record.fields["tradeId"] = trade.exchange_trade_id;
    record.fields["side"] = trade.side;
    record.fields["px"] = decimal_to_string(trade.price);
    record.fields["sz"] = decimal_to_string(trade.size);
    record.fields["price"] = decimal_to_string(trade.price);
    if (trade.trade_count > 0)
    {
        record.fields["count"] = std::to_string(trade.trade_count);
    }
    if (trade.sequence_id > 0)
    {
        record.fields["seqId"] = std::to_string(trade.sequence_id);
    }

    put_feature_fields(record.fields, feature);
    return record;
}

void populate_changed_fields(StreamRecord& record, const std::map<std::string, std::string>& previous_fields)
{
    for (const auto& [key, value] : record.fields)
    {
        const auto it = previous_fields.find(key);
        if (it == previous_fields.end() || it->second != value)
        {
            record.changed_fields.push_back(key);
        }
    }

    for (const auto& [key, _] : previous_fields)
    {
        if (record.fields.find(key) == record.fields.end())
        {
            record.changed_fields.push_back(key);
        }
    }
}
