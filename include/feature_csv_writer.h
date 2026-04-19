#pragma once 

#include "feature_builder.h"
#include <fstream>
#include <stdexcept>
#include <string>

namespace trading
{
class FeatureCsvWriter
{
public:
    explicit FeatureCsvWriter(const std::string& path);
    void write(const feature_row& row);
private:
    void write_header();
private:
    std::ofstream m_out;
};
}  // namespace trading
