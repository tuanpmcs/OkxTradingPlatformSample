#pragma once

#include "feature_builder.h"

#include <fstream>
#include <string>

namespace trading
{

class feature_csv_writer
{
public:
	explicit feature_csv_writer(const std::string& path);
	void write(const feature_row& row);

private:
	void write_header();

private:
	std::ofstream m_out;
};

}  // namespace trading
