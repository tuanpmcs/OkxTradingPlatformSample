#include "features/feature_csv_writer.hpp"

#include <stdexcept>

namespace trading
{

FeatureCsvWriter::FeatureCsvWriter(const std::string& path)
{
	m_out.open(path, std::ios::out | std::ios::trunc);
	if (!m_out.is_open())
	{
		throw std::runtime_error("Failed to open feature csv output: " + path);
	}
	write_header();
}

void FeatureCsvWriter::write_header()
{
	m_out
		<< "inst_id,book_ts,book_recv_ts,book_seq_id,"
		<< "best_bid_px,best_ask_px,best_bid_sz,best_ask_sz,"
		<< "mid_price,spread,rel_spread,microprice,"
		<< "imbalance_l1,imbalance_l5,bid_vol_l5,ask_vol_l5,"
		<< "weighted_bid_depth,weighted_ask_depth,"
		<< "trade_count,buy_count,sell_count,"
		<< "trade_volume,buy_volume,sell_volume,trade_imbalance,"
		<< "trade_vwap,trade_vwap_dev_from_mid,"
		<< "prev_mid_price,prev_spread,delta_mid_price,delta_spread,delta_imbalance_l5\n";
}

void FeatureCsvWriter::write(const FeatureRow& row)
{
	m_out
		<< row.inst_id << ','
		<< row.book_ts << ','
		<< row.book_recv_ts << ','
		<< row.book_seq_id << ','
		<< row.best_bid_px << ','
		<< row.best_ask_px << ','
		<< row.best_bid_sz << ','
		<< row.best_ask_sz << ','
		<< row.mid_price << ','
		<< row.spread << ','
		<< row.rel_spread << ','
		<< row.microprice << ','
		<< row.imbalance_l1 << ','
		<< row.imbalance_l5 << ','
		<< row.bid_vol_l5 << ','
		<< row.ask_vol_l5 << ','
		<< row.weighted_bid_depth << ','
		<< row.weighted_ask_depth << ','
		<< row.trade_count << ','
		<< row.buy_count << ','
		<< row.sell_count << ','
		<< row.trade_volume << ','
		<< row.buy_volume << ','
		<< row.sell_volume << ','
		<< row.trade_imbalance << ','
		<< row.trade_vwap << ','
		<< row.trade_vwap_dev_from_mid << ','
		<< row.prev_mid_price << ','
		<< row.prev_spread << ','
		<< row.delta_mid_price << ','
		<< row.delta_spread << ','
		<< row.delta_imbalance_l5 << '\n';
	m_out.flush();
}

}  // namespace trading
