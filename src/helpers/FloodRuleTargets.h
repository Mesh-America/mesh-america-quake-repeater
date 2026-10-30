#pragma once

// Rule targets are mutually exclusive. The repeater stores one tagged name;
// the room engine and portable policy users retain their existing fields.
// Preserve array references so explicit FPF7 serialization keeps both fixed
// width fields, including the zero-filled inactive name.
namespace FloodRuleTargets {
template<typename Entry>
auto scopeNameImpl(const Entry& entry, int) -> decltype(entry.scopeName()) {
  return entry.scopeName();
}
template<typename Entry>
auto scopeNameImpl(const Entry& entry, long) -> decltype((entry.scope_name)) {
  return entry.scope_name;
}
template<typename Entry>
auto regionNameImpl(const Entry& entry, int) -> decltype(entry.regionName()) {
  return entry.regionName();
}
template<typename Entry>
auto regionNameImpl(const Entry& entry, long) -> decltype((entry.target_region_name)) {
  return entry.target_region_name;
}
template<typename Entry>
auto scopeName(const Entry& entry) -> decltype(scopeNameImpl(entry, 0)) {
  return scopeNameImpl(entry, 0);
}
template<typename Entry>
auto regionName(const Entry& entry) -> decltype(regionNameImpl(entry, 0)) {
  return regionNameImpl(entry, 0);
}
} // namespace FloodRuleTargets
