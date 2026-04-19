#pragma once

#include <array>
#include <charconv>
#include <cstdint>
#include <iostream>
#include <limits>
#include <optional>
#include <ostream>
#include <string>
#include <string_view>
#include <vector>

#include <boost/multiprecision/cpp_dec_float.hpp>
#include <simdjson.h>

using DoubleType = boost::multiprecision::number<
    boost::multiprecision::cpp_dec_float<8>,
    boost::multiprecision::et_off
>;

struct Error {
    std::string id;
    std::string event;
    std::string code;
    std::string msg;
    std::string connection_id;
};

enum class Channel : std::uint8_t {
    BOOKS,
    BOOKS5,
    TRADES
};

struct Arg {
    Channel channel{};
    std::string instrument_id;
};

struct Book {
    DoubleType price{};
    DoubleType quantity{};
    std::uint32_t deprecated_value{};
    std::uint32_t order_count{};
};

struct Books {
    std::vector<Book> bids{};
    std::vector<Book> asks{};
    std::uint64_t exchange_ts_ms{};
    std::uint64_t recv_ts_ms{};
    std::uint64_t sequence_id{};
    std::string instrument_id;
};

struct Books5 {
    std::array<Book, 5> bids{};
    std::array<Book, 5> asks{};
    std::uint64_t exchange_ts_ms{};
    std::uint64_t recv_ts_ms{};
    std::uint64_t sequence_id{};
    std::string instrument_id;
};

struct Trade {
    std::string instrument_id;
    std::string exchange_trade_id;
    DoubleType price{};
    DoubleType size{};
    std::string side;
    std::uint64_t exchange_ts_ms{};
    std::uint64_t recv_ts_ms{};
    std::uint32_t trade_count{};
    std::string exchange;
    std::uint64_t sequence_id{};
};

using Trades = std::vector<Trade>;

inline constexpr std::string_view to_string(const Channel channel) noexcept {
    switch (channel) {
        case Channel::BOOKS:  return "BOOKS";
        case Channel::BOOKS5: return "BOOKS5";
        case Channel::TRADES: return "TRADES";
        default:              return "UNKNOWN_CHANNEL";
    }
}

inline std::ostream& operator<<(std::ostream& os, const Channel channel) {
    os << to_string(channel);
    return os;
}

inline std::ostream& operator<<(std::ostream& os, const Error& value) {
    os << "Error{"
       << "id=" << value.id
       << ", event=" << value.event
       << ", code=" << value.code
       << ", msg=" << value.msg
       << ", connection_id=" << value.connection_id
       << "}";
    return os;
}

inline std::ostream& operator<<(std::ostream& os, const Arg& value) {
    os << "Arg{"
       << "channel=" << value.channel
       << ", instrument_id=" << value.instrument_id
       << "}";
    return os;
}

inline std::ostream& operator<<(std::ostream& os, const Book& value) {
    os << "Book{"
       << "price=" << value.price
       << ", quantity=" << value.quantity
       << ", deprecated_value=" << value.deprecated_value
       << ", order_count=" << value.order_count
       << "}";
    return os;
}

template <typename T>
inline std::ostream& print_vector(std::ostream& os, const std::vector<T>& values) {
    os << "[";
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i > 0) {
            os << ", ";
        }
        os << values[i];
    }
    os << "]";
    return os;
}

template <typename T, std::size_t N>
inline std::ostream& print_array(std::ostream& os, const std::array<T, N>& values) {
    os << "[";
    for (std::size_t i = 0; i < N; ++i) {
        if (i > 0) {
            os << ", ";
        }
        os << values[i];
    }
    os << "]";
    return os;
}

inline std::ostream& operator<<(std::ostream& os, const Books& value) {
    os << "Books{"
       << "bids=";
    print_vector(os, value.bids);
    os << ", asks=";
    print_vector(os, value.asks);
    os << ", exchange_ts_ms=" << value.exchange_ts_ms
       << ", recv_ts_ms=" << value.recv_ts_ms
       << ", sequence_id=" << value.sequence_id
       << ", instrument_id=" << value.instrument_id
       << "}";
    return os;
}

inline std::ostream& operator<<(std::ostream& os, const Books5& value) {
    os << "Books5{"
       << "bids=";
    print_array(os, value.bids);
    os << ", asks=";
    print_array(os, value.asks);
    os << ", exchange_ts_ms=" << value.exchange_ts_ms
       << ", recv_ts_ms=" << value.recv_ts_ms
       << ", sequence_id=" << value.sequence_id
       << ", instrument_id=" << value.instrument_id
       << "}";
    return os;
}

inline std::ostream& operator<<(std::ostream& os, const Trade& value) {
    os << "Trade{"
       << "instrument_id=" << value.instrument_id
       << ", exchange_trade_id=" << value.exchange_trade_id
       << ", price=" << value.price
       << ", size=" << value.size
       << ", side=" << value.side
       << ", exchange_ts_ms=" << value.exchange_ts_ms
       << ", recv_ts_ms=" << value.recv_ts_ms
       << ", trade_count=" << value.trade_count
       << ", exchange=" << value.exchange
       << ", sequence_id=" << value.sequence_id
       << "}";
    return os;
}

inline std::ostream& print_trades(std::ostream& os, const Trades& trades) {
    os << "Trades";
    return print_vector(os, trades);
}

class Parser {
public:
    explicit Parser(std::string_view json)
        : _json(json) {}

    std::optional<Arg> parse_arg();
    std::optional<Books> parse_books();
    std::optional<Books5> parse_books5();
    std::optional<Trade> parse_trade();
    std::optional<Trades> parse_trades();

private:
    static std::optional<Channel> parse_channel(std::string_view channel);
    static std::optional<DoubleType> parse_decimal(std::string_view sv);
    static std::optional<std::uint32_t> parse_u32(std::string_view sv);
    static std::optional<std::uint64_t> parse_u64(std::string_view sv);

    static std::optional<Book> parse_book_level(simdjson::ondemand::array arr);
    static std::optional<Trade> parse_trade_object(simdjson::ondemand::object obj);

    static std::optional<std::uint64_t> parse_u64_field(simdjson::ondemand::object& obj, const char* key);
    static std::optional<std::uint32_t> parse_u32_field(simdjson::ondemand::object& obj, const char* key);

private:
    simdjson::ondemand::parser _parser;
    simdjson::padded_string _json;
};
