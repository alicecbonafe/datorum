class DatorumException(Exception): ...


# MODEL


class DatorumModelException(DatorumException): ...


class NoFilePathException(DatorumModelException): ...


class OrphanSourceException(DatorumModelException): ...


class InvalidIdentifierException(DatorumModelException): ...


# SERVICE


class DatorumServiceException(DatorumException): ...


class InferenceException(DatorumServiceException): ...


class ScraperException(DatorumServiceException): ...


class ChunkerException(DatorumServiceException): ...
