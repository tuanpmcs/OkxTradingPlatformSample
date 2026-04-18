#pragma once

#include "types.h"

#include <cstdint>
#include <deque>
#include <fstream>
#include <map>
#include <optional>
#include <string>
#include <vector>

struct StreamRecord
{
	std::int64_t					   ts_ms{0};
	double							   price{0.0};
	double							   change{0.0};
	std::string						   source;
	std::string						   raw_json;
	std::map<std::string, std::string> fields;
	std::vector<std::string>		   changed_fields;
};

struct FeatureSnapshot
{
	double mid_price{0.0};
	double spread{0.0};
	double imbalance{0.0};
	double trade_volume{0.0};
	double trade_imbalance{0.0};
};

class MarketEventListener
{
public:
	virtual ~MarketEventListener() = default;
	virtual void on_trades(const Trades& trades, const std::string& raw_json) = 0;
	virtual void on_books5(const Books5& books5, const std::string& raw_json) = 0;
	virtual void on_books(const Books& books, const std::string& raw_json) = 0;
};

class MarketEventDispatcher
{
public:
	explicit MarketEventDispatcher(MarketEventListener& listener);
	bool dispatch(const std::string& payload);

private:
	MarketEventListener& _listener;
};

class CsvTickWriter
{
public:
	explicit CsvTickWriter(const std::string& path);
	void write(const StreamRecord& tick);

private:
	static std::string infer_event_type(const std::string& channel);
	void write_header();

private:
	std::ofstream _out;
};

class FeatureAccumulator
{
public:
	explicit FeatureAccumulator(std::int64_t trade_window_ms = 5000);
	void observe_books(const Books& books);
	void observe_books5(const Books5& books5);
	void observe_trade(const Trade& trade);
	void prune(std::int64_t now_ms);
	FeatureSnapshot snapshot() const;

private:
	struct TradeSample
	{
		std::int64_t ts_ms{0};
		double		 abs_size{0.0};
		double		 signed_size{0.0};
	};

private:
	std::int64_t		  _trade_window_ms{5000};
	std::optional<double> _bid_px;
	std::optional<double> _ask_px;
	std::optional<double> _bid_sz;
	std::optional<double> _ask_sz;
	std::deque<TradeSample> _trades;
};

StreamRecord make_stream_record_from_books(const Books& books,
									   const FeatureSnapshot& feature,
									   std::optional<double> last_price,
									   const std::string& raw_json,
									   const std::string& channel);

StreamRecord make_stream_record_from_trade(const Trade& trade,
								   const FeatureSnapshot& feature,
								   std::optional<double> last_price,
								   const std::string& raw_json);

void populate_changed_fields(StreamRecord& record, const std::map<std::string, std::string>& previous_fields);
