#pragma once

#include "types.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <limits>
#include <optional>
#include <ostream>
#include <string>
#include <vector>

namespace trading
{
using double_type = double;

struct feature_row
{
	std::string inst_id;

	std::uint64_t book_ts{};
	std::uint64_t book_recv_ts{};
	std::uint64_t book_seq_id{};

	double_type best_bid_px{};
	double_type best_ask_px{};
	double_type best_bid_sz{};
	double_type best_ask_sz{};

	double_type mid_price{};
	double_type spread{};
	double_type rel_spread{};
	double_type microprice{};
	double_type imbalance_l1{};
	double_type imbalance_l5{};
	double_type bid_vol_l5{};
	double_type ask_vol_l5{};
	double_type weighted_bid_depth{};
	double_type weighted_ask_depth{};

	std::size_t trade_count{};
	std::size_t buy_count{};
	std::size_t sell_count{};

	double_type trade_volume{};
	double_type buy_volume{};
	double_type sell_volume{};
	double_type trade_imbalance{};

	double_type trade_vwap{};
	double_type trade_vwap_dev_from_mid{};

	double_type prev_mid_price{};
	double_type prev_spread{};
	double_type delta_mid_price{};
	double_type delta_spread{};
	double_type delta_imbalance_l5{};
};

inline std::ostream& operator<<(std::ostream& os, const feature_row& row)
{
	os
		<< "feature_row{" << "inst_id=" << row.inst_id << ", book_ts=" << row.book_ts << ", seq_id="
		<< row.book_seq_id << ", best_bid_px=" << row.best_bid_px << ", best_ask_px=" << row.best_ask_px
		<< ", mid_price=" << row.mid_price << ", spread=" << row.spread << ", microprice=" << row.microprice
		<< ", imbalance_l1=" << row.imbalance_l1 << ", imbalance_l5=" << row.imbalance_l5
		<< ", trade_count=" << row.trade_count << ", buy_count=" << row.buy_count
		<< ", sell_count=" << row.sell_count << ", trade_volume=" << row.trade_volume
		<< ", buy_volume=" << row.buy_volume << ", sell_volume=" << row.sell_volume
		<< ", trade_imbalance=" << row.trade_imbalance << ", trade_vwap=" << row.trade_vwap
		<< ", trade_vwap_dev_from_mid=" << row.trade_vwap_dev_from_mid
		<< ", delta_mid_price=" << row.delta_mid_price << ", delta_spread=" << row.delta_spread
		<< ", delta_imbalance_l5=" << row.delta_imbalance_l5 << "}";
	return os;
}

class feature_builder
{
public:
	struct config
	{
		std::uint64_t trade_lookback_ms{100};
		bool use_exchange_ts_for_alignment{true};
	};

public:
	feature_builder()
		: feature_builder(config{})
	{
	}

	explicit feature_builder(config cfg)
		: m_cfg(cfg)
	{
	}

	void on_trade(const Trade& t)
	{
		m_trades.push_back(t);
		const auto now_ts = choose_trade_time(t);
		evict_old_trades(now_ts);
	}

	std::optional<feature_row> on_books(const Books5& b)
	{
		if (!is_valid_book(b))
		{
			return std::nullopt;
		}

		const std::uint64_t now_ts = choose_book_time(b);
		evict_old_trades(now_ts);

		feature_row row{};
		row.inst_id = b.instrument_id;
		row.book_ts = b.exchange_ts_ms;
		row.book_recv_ts = b.recv_ts_ms;
		row.book_seq_id = b.sequence_id;

		row.best_bid_px = to_scalar(b.bids[0].price);
		row.best_ask_px = to_scalar(b.asks[0].price);
		row.best_bid_sz = to_scalar(b.bids[0].quantity);
		row.best_ask_sz = to_scalar(b.asks[0].quantity);

		row.mid_price = compute_mid_price(b);
		row.spread = compute_spread(b);
		row.rel_spread = safe_div(row.spread, row.mid_price);
		row.microprice = compute_microprice(b);
		row.imbalance_l1 = compute_level_imbalance(b, 1);
		row.imbalance_l5 = compute_level_imbalance(b, 5);
		row.bid_vol_l5 = sum_bid_volume(b, 5);
		row.ask_vol_l5 = sum_ask_volume(b, 5);
		row.weighted_bid_depth = compute_weighted_bid_depth(b, 5);
		row.weighted_ask_depth = compute_weighted_ask_depth(b, 5);

		fill_trade_features(now_ts, row);

		row.prev_mid_price = m_prev_mid_price.value_or(row.mid_price);
		row.prev_spread = m_prev_spread.value_or(row.spread);
		row.delta_mid_price = row.mid_price - row.prev_mid_price;
		row.delta_spread = row.spread - row.prev_spread;
		row.delta_imbalance_l5 = row.imbalance_l5 - m_prev_imbalance_l5.value_or(row.imbalance_l5);

		m_prev_mid_price = row.mid_price;
		m_prev_spread = row.spread;
		m_prev_imbalance_l5 = row.imbalance_l5;
		m_last_book = b;

		return row;
	}

	std::optional<feature_row> on_books(const Books& b)
	{
		if (b.bids.empty() || b.asks.empty())
		{
			return std::nullopt;
		}

		Books5 b5;
		b5.instrument_id = b.instrument_id;
		b5.exchange_ts_ms = b.exchange_ts_ms;
		b5.recv_ts_ms = b.recv_ts_ms;
		b5.sequence_id = b.sequence_id;

		const auto bid_levels = std::min<std::size_t>(5, b.bids.size());
		const auto ask_levels = std::min<std::size_t>(5, b.asks.size());
		for (std::size_t i = 0; i < bid_levels; ++i)
		{
			b5.bids[i] = b.bids[i];
		}
		for (std::size_t i = 0; i < ask_levels; ++i)
		{
			b5.asks[i] = b.asks[i];
		}

		return on_books(b5);
	}

private:
	config m_cfg;
	std::deque<Trade> m_trades{};
	std::optional<Books5> m_last_book{};

	std::optional<double_type> m_prev_mid_price{};
	std::optional<double_type> m_prev_spread{};
	std::optional<double_type> m_prev_imbalance_l5{};

private:
	static constexpr double_type k_eps = 1e-12;

private:
	static double_type to_scalar(const ::double_type& value)
	{
		return value.convert_to<double>();
	}

	std::uint64_t choose_trade_time(const Trade& t) const
	{
		return m_cfg.use_exchange_ts_for_alignment ? t.exchange_ts_ms : t.recv_ts_ms;
	}

	std::uint64_t choose_book_time(const Books5& b) const
	{
		return m_cfg.use_exchange_ts_for_alignment ? b.exchange_ts_ms : b.recv_ts_ms;
	}

	void evict_old_trades(std::uint64_t now_ts)
	{
		const std::uint64_t cutoff = (now_ts > m_cfg.trade_lookback_ms) ? (now_ts - m_cfg.trade_lookback_ms) : 0;

		while (!m_trades.empty())
		{
			const auto& t = m_trades.front();
			const auto trade_ts = choose_trade_time(t);
			if (trade_ts >= cutoff)
			{
				break;
			}
			m_trades.pop_front();
		}
	}

	static bool is_valid_book(const Books5& b)
	{
		if (to_scalar(b.bids[0].price) <= 0.0 || to_scalar(b.asks[0].price) <= 0.0)
		{
			return false;
		}
		if (to_scalar(b.bids[0].quantity) < 0.0 || to_scalar(b.asks[0].quantity) < 0.0)
		{
			return false;
		}
		if (to_scalar(b.bids[0].price) > to_scalar(b.asks[0].price))
		{
			return false;
		}
		return true;
	}

	static double_type safe_div(double_type num, double_type den)
	{
		if (std::abs(den) < k_eps)
		{
			return 0.0;
		}
		return num / den;
	}

	static double_type compute_mid_price(const Books5& b)
	{
		return (to_scalar(b.bids[0].price) + to_scalar(b.asks[0].price)) / 2.0;
	}

	static double_type compute_spread(const Books5& b)
	{
		return to_scalar(b.asks[0].price) - to_scalar(b.bids[0].price);
	}

	static double_type compute_microprice(const Books5& b)
	{
		const auto bid_px = to_scalar(b.bids[0].price);
		const auto ask_px = to_scalar(b.asks[0].price);
		const auto bid_sz = to_scalar(b.bids[0].quantity);
		const auto ask_sz = to_scalar(b.asks[0].quantity);
		const auto den = bid_sz + ask_sz;
		if (std::abs(den) < k_eps)
		{
			return (bid_px + ask_px) / 2.0;
		}
		return (ask_px * bid_sz + bid_px * ask_sz) / den;
	}

	static double_type sum_bid_volume(const Books5& b, std::size_t levels)
	{
		const std::size_t n = std::min<std::size_t>(levels, b.bids.size());
		double_type total = 0.0;
		for (std::size_t i = 0; i < n; ++i)
		{
			total += to_scalar(b.bids[i].quantity);
		}
		return total;
	}

	static double_type sum_ask_volume(const Books5& b, std::size_t levels)
	{
		const std::size_t n = std::min<std::size_t>(levels, b.asks.size());
		double_type total = 0.0;
		for (std::size_t i = 0; i < n; ++i)
		{
			total += to_scalar(b.asks[i].quantity);
		}
		return total;
	}

	static double_type compute_level_imbalance(const Books5& b, std::size_t levels)
	{
		const auto bid_vol = sum_bid_volume(b, levels);
		const auto ask_vol = sum_ask_volume(b, levels);
		return safe_div(bid_vol - ask_vol, bid_vol + ask_vol);
	}

	static double_type compute_weighted_bid_depth(const Books5& b, std::size_t levels)
	{
		const std::size_t n = std::min<std::size_t>(levels, b.bids.size());
		double_type total = 0.0;
		for (std::size_t i = 0; i < n; ++i)
		{
			const double_type weight = 1.0 / static_cast<double_type>(i + 1);
			total += to_scalar(b.bids[i].quantity) * weight;
		}
		return total;
	}

	static double_type compute_weighted_ask_depth(const Books5& b, std::size_t levels)
	{
		const std::size_t n = std::min<std::size_t>(levels, b.asks.size());
		double_type total = 0.0;
		for (std::size_t i = 0; i < n; ++i)
		{
			const double_type weight = 1.0 / static_cast<double_type>(i + 1);
			total += to_scalar(b.asks[i].quantity) * weight;
		}
		return total;
	}

	void fill_trade_features(std::uint64_t now_ts, feature_row& row) const
	{
		double_type notional = 0.0;

		for (const auto& t : m_trades)
		{
			if (t.instrument_id != row.inst_id)
			{
				continue;
			}

			const auto t_ts = choose_trade_time(t);
			if (t_ts > now_ts)
			{
				continue;
			}

			row.trade_count += 1;
			const auto sz = to_scalar(t.size);
			const auto px = to_scalar(t.price);
			row.trade_volume += sz;
			notional += px * sz;

			if (t.side == "buy")
			{
				row.buy_count += 1;
				row.buy_volume += sz;
			}
			else if (t.side == "sell")
			{
				row.sell_count += 1;
				row.sell_volume += sz;
			}
		}

		row.trade_imbalance = safe_div(row.buy_volume - row.sell_volume, row.buy_volume + row.sell_volume);
		row.trade_vwap = (row.trade_volume > 0.0) ? (notional / row.trade_volume) : row.mid_price;
		row.trade_vwap_dev_from_mid = safe_div(row.trade_vwap - row.mid_price, row.mid_price);
	}
};

}  // namespace trading
